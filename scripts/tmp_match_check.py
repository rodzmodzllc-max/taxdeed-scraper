"""Temporary, value-free comparisons only (yes/no, earlier/later)."""
import json, subprocess, sys
subprocess.run([sys.executable, "scripts/harvest_clerk_statements.py", "--counties", "Citrus", "--report"], check=True)
res = json.load(open("out/clerk_statements.json"))
for st in res["statements"]:
    print("case matches screenshot:", st["case_no"] == "2024-0075TD")
    print("current statement present:", st["purchase_statement"] is not None)
    for label, rec in [("current", st["purchase_statement"])] + [(f"history[{i}]", r) for i, r in enumerate(st["purchase_statement_history"])]:
        if not rec: continue
        t, v, d = rec["total_due"], rec["valid_through"], rec.get("statement_date")
        print(f"{label}: total vs screenshot {'higher' if t > 27689.42 else 'lower' if t < 27689.42 else 'equal'}; "
              f"valid_through vs 2026-08-31 {'later' if v and v > '2026-08-31' else 'earlier' if v and v < '2026-08-31' else 'equal' if v else 'none'}; "
              f"statement date present {bool(d)}; expired today {v is not None and v < res['observed_on']}")
