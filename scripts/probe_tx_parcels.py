#!/usr/bin/env python3
"""Value-free reachability probe for the Texas parcel enrichment sources
(TX enrichment, 2026-10-27): runs as the manual, read-only
`job=evidence` with `evidence_scope=tx_parcels`.

For each named county it downloads the TxGIO StratMap 2026 county shapefile
(the county_file transport's own URL) and prints the HTTP outcome, the byte
count, the record count and whether each mapped attribute exists - never an
attribute value. For the HCAD layer it asks only for the record count.
Nothing is written anywhere; no database credential is used.

    python3 scripts/probe_tx_parcels.py [--county Navarro --county Jasper]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

USER_AGENT = "taxdeed-scraper tx-parcel-probe (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"


def probe_county(cfg, county: str) -> dict:
    out = {"county": county, "url": cfg.file_url(county)}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "county.zip"
            req = urllib.request.Request(out["url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=600) as resp, open(path, "wb") as fh:
                out["status"] = resp.status
                while chunk := resp.read(1 << 20):
                    fh.write(chunk)
            out["bytes"] = path.stat().st_size
            import shapefile  # noqa: PLC0415
            with zipfile.ZipFile(path) as z:
                dbf = [n for n in z.namelist() if n.lower().endswith(".dbf")]
                prj = [n for n in z.namelist() if n.lower().endswith(".prj")]
                out["members"] = sorted(n.rsplit(".", 1)[-1].lower() for n in z.namelist())
                from harvesters.enrichment import county_file as CF  # noqa: PLC0415
                out["prj_wgs84"] = bool(prj) and CF.is_wgs84_geographic(z.read(prj[0]).decode("utf-8", "replace"))
                z.extract(dbf[0], tmp)
            with open(Path(tmp) / dbf[0], "rb") as fh:
                r = shapefile.Reader(dbf=fh)
                names = {f[0] for f in r.fields[1:]}
                out["records"] = len(r)
            wanted = {*cfg.id_fields(county), *cfg.field_map.values(), *[a for a, c, _ in cfg.conditional_map.values()],
                      *[c for a, c, _ in cfg.conditional_map.values()]}
            out["attributes_present"] = {a: a in names for a in sorted(wanted)}
    except Exception as exc:  # noqa: BLE001 - a failed read is reported, never retried around
        out["error"] = f"{type(exc).__name__}: {getattr(exc, 'code', '') or str(exc)[:120]}"
    return out


def probe_hcad(cfg) -> dict:
    q = urllib.parse.urlencode({"where": "1=1", "returnCountOnly": "true", "f": "json"})
    try:
        req = urllib.request.Request(f"{cfg.layer_url}/query?{q}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return {"source_id": cfg.source_id, "status": resp.status, "count": data.get("count"), "error": data.get("error")}
    except Exception as exc:  # noqa: BLE001
        return {"source_id": cfg.source_id, "error": f"{type(exc).__name__}: {getattr(exc, 'code', '') or str(exc)[:120]}"}


def main(argv=None) -> int:
    import permission_gate as _PG  # noqa: PLC0415
    _PG.install_discovery_guard("probe_tx_parcels")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--county", action="append", default=[])
    a = ap.parse_args(argv)
    from harvesters.enrichment import sources as S  # noqa: PLC0415
    counties = a.county or ["Navarro", "Jasper"]
    report = {"stratmap": [probe_county(S.TX_STRATMAP, c) for c in counties if S.TX_STRATMAP.covers(c)],
              "hcad": probe_hcad(S.TX_HCAD)}
    out = REPO / "out" / "public" / "tx-parcel-probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
