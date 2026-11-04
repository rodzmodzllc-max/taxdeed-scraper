"""Value-free read of the three Texas vendor sources the owner unblocked on
2026-10-26 (tx_pbfcm, tx_mvba, tx_govease), from the GitHub runner.

Manual only (`job=evidence`, `evidence_scope=tx_vendors`). It runs the real
harvesters (harvesters/texas_vendors.py) under the discovery guard (every
request needs the source's recorded `discover` permission) and prints, per
source and county: the read status (COMPLETE / EMPTY / INCOMPLETE / FAILED),
row count, document count and the document signals; per source: how many
rows carry each field. Never a value, URL path, account, owner or amount.
Nothing is written to any database.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def summarize(source_id: str, rows: list[dict], stats: dict) -> list[str]:
    out = [f"== {source_id}: rows={len(rows)} complete={stats.get('complete')} requests={stats.get('requests')} "
           f"index_errors={sorted(stats.get('index_errors', {}).values()) or 'none'}"]
    for county, u in sorted(stats.get("units", {}).items()):
        signals = collections.Counter(d.get("signal", "") for d in u.get("documents", []))
        out.append(f"   {county:16s} {u['status']:10s} rows={u['rows']:4d} docs={len(u.get('documents', []))} "
                   f"ledgers={dict(sorted(u['ledgers'].items()))} signals={dict(sorted(signals.items()))}")
    fill = collections.Counter(k for r in rows for k, v in r.items() if v not in (None, ""))
    out.append(f"   fields filled: {dict(sorted(fill.items()))}")
    ledgers = collections.Counter(r.get("source") for r in rows)
    out.append(f"   rows by ledger: {dict(sorted(ledgers.items()))}")
    for k in ("skipped_links", "skipped_rows", "online", "unknown_counties"):
        if stats.get(k):
            out.append(f"   {k}: {stats[k]}")
    return out


def main(argv=None) -> int:
    # Source permission for discovery (data/source_permissions.csv, operation
    # "discover"): every request below is refused before any connection unless
    # its URL belongs to a source with an in-date discover permission.
    import permission_gate as _PG  # noqa: PLC0415
    _PG.install_discovery_guard("capture_tx_vendors")
    from harvesters import texas_vendors as V  # noqa: PLC0415

    failed = 0
    for sid, fn in (("tx_pbfcm", V.harvest_pbfcm), ("tx_mvba", V.harvest_mvba), ("tx_govease", V.harvest_govease)):
        stats: dict = {}
        try:
            rows = fn(stats=stats)
        except Exception as exc:  # noqa: BLE001 - one source's failure is reported, not fatal
            print(f"== {sid}: ERROR {type(exc).__name__}")
            failed += 1
            continue
        print("\n".join(summarize(sid, rows, stats)))
    return 1 if failed == 3 else 0


if __name__ == "__main__":
    sys.exit(main())
