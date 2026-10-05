"""Temporary, value-free: does the VERIFIED Citrus statement equal the figures
on the customer's own screenshot (case 2024-0075TD, Total Due from Purchaser
27,689.42, if received by 8/31/2026)? Prints yes/no only."""
import json, subprocess, sys
subprocess.run([sys.executable, "scripts/harvest_clerk_statements.py", "--counties", "Citrus"], check=True)
res = json.load(open("out/clerk_statements.json"))
for st in res["statements"]:
    cur = st["purchase_statement"]
    print("case matches screenshot:", st["case_no"] == "2024-0075TD")
    print("total_due matches screenshot:", cur["total_due"] == 27689.42)
    print("valid_through matches screenshot:", cur["valid_through"] == "2026-08-31")
    c = cur["components"]
    print("opening_bid matches grid base bid 2606.70:", c["opening_bid"] == 2606.70)
    print("opening bid + 4 additions == printed total:", round(c["opening_bid"] + c["interest"] + c["omitted_taxes"] + c["doc_stamps"] + c["recording_fees"], 2) == cur["total_due"])
