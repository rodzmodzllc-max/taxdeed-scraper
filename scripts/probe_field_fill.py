#!/usr/bin/env python3
"""Value-free field FILL RATES for every configured ArcGIS layer (six-state
expansion, 2026-09-30): the expansion inventory layers
(harvesters/otc/adapters/expansion.py) and the statewide parcel layers
(harvesters/enrichment/sources.py).

For each layer: every field's name / type / alias (no cap), then a sample of
up to --sample features (outFields=*, no geometry) and, per field, how many
sampled features carry a non-empty value, plus the SHAPE of the most common
values of the configured mapping fields (each digit -> 9, each letter -> A).
Never a value. Used to map columns to the attributes the live layer actually
fills, instead of trusting metadata alone.

    python3 scripts/probe_field_fill.py                 # every configured layer
    python3 scripts/probe_field_fill.py --state SC
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
from harvesters.enrichment.sources import PARCEL_SOURCES  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402

USER_AGENT = "taxdeed-scraper field-fill probe (+https://github.com/rodzmodzllc-max/taxdeed-scraper; GitHub Actions)"


def shape(v) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", str(v).strip()))[:40]


def filled(v) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return bool(s) and s.upper() not in ("NULL", "N/A", "NONE")


def layers(state: str | None) -> list[tuple[str, str, dict[str, str], str]]:
    """(label, layer_url, {column: attribute}, where) for every configured layer.
    A statewide layer is sampled inside the county the product's inventory
    uses (so an identifier's shape can be compared with that county's list)."""
    out = []
    for st, srcs in EX.SOURCES.items():
        if state and st != state:
            continue
        for src in srcs:
            cfg = src.config
            if src.kind != "arcgis":
                continue
            fm = {k: v for k, v in vars(cfg.fields).items() if isinstance(v, str) and v}
            out.append((f"{st} {cfg.source_id}", cfg.layer_url, fm, "1=1"))
    for st, cfg in PARCEL_SOURCES.items():
        if state and st != state:
            continue
        fm = {"id": cfg.id_field, **cfg.field_map}
        if cfg.county_field:
            fm["county"] = cfg.county_field
        counties = [src.config.county for src in EX.SOURCES.get(st, ())]
        where = f"UPPER({cfg.county_field}) = '{counties[0].upper()}'" if cfg.county_field and counties else "1=1"
        out.append((f"{st} {cfg.source_id} (statewide)", cfg.layer_url, fm, where))
    return out


def probe(session, label: str, url: str, fmap: dict[str, str], sample: int, where: str = "1=1") -> dict:
    rec: dict = {"label": label, "layer": url}
    meta = session.get(url + "?f=json", timeout=60).json()
    fields = meta.get("fields") or []
    rec["field_count"] = len(fields)
    q = session.get(url + "/query?" + urlencode({"where": where, "outFields": "*", "returnGeometry": "false",
                                                  "resultRecordCount": sample, "f": "json"}), timeout=120).json()
    feats = q.get("features") or []
    if "error" in q:
        rec["error"] = str(q["error"].get("message") or q["error"])[:200]
    rec["sampled"] = len(feats)
    attrs = [f.get("attributes") or {} for f in feats]
    rec["fields"] = [{"name": f.get("name"), "type": (f.get("type") or "").replace("esriFieldType", ""),
                      "alias": f.get("alias") if f.get("alias") != f.get("name") else "",
                      "filled": sum(1 for a in attrs if filled(a.get(f.get("name"))))} for f in fields]
    names = {f.get("name") for f in fields}
    rec["mapping"] = {col: {"attribute": attr, "exists": attr in names,
                            "filled": sum(1 for a in attrs if filled(a.get(attr))),
                            "shapes": dict(Counter(shape(a.get(attr)) for a in attrs if filled(a.get(attr))).most_common(3))}
                      for col, attr in fmap.items()}
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", default=None)
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--out", default=str(REPO / "out" / "public" / "field-fill.json"))
    a = ap.parse_args(argv)
    import requests  # noqa: PLC0415
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    report = []
    for label, url, fmap, where in layers(a.state):
        try:
            rec = probe(s, label, url, fmap, a.sample, where)
        except Exception as exc:  # noqa: BLE001 - a failed probe is reported, never guessed
            rec = {"label": label, "layer": url, "error": f"{type(exc).__name__}"}
        report.append(rec)
        print(f"## {label}  where={where}  sampled={rec.get('sampled')} fields={rec.get('field_count')} {('error=' + rec['error']) if rec.get('error') else ''}")
        for f in rec.get("fields", []):
            print(f"   {f['name']}:{f['type']}{('(' + f['alias'] + ')') if f['alias'] else ''} filled={f['filled']}/{rec['sampled']}")
        for col, m in (rec.get("mapping") or {}).items():
            print(f"   MAP {col} <- {m['attribute']} exists={m['exists']} filled={m['filled']}/{rec['sampled']} shapes={m['shapes']}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
