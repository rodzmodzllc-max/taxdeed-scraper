"""Temporary: print the public statute text for F.S. 197.502(6)-(7) and 197.542(1)."""
import re, html, requests
for sec in ("0197.502", "0197.542"):
    u = f"http://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0197/Sections/{sec}.html"
    r = requests.get(u, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    t = html.unescape(re.sub(r"<[^>]+>", " ", r.text)); t = re.sub(r"\s+", " ", t)
    print(f"=== {sec} status {r.status_code} ===")
    yr = re.search(r"The (\d{4}) Florida Statutes", t); print("version:", yr.group(1) if yr else "?")
    if sec == "0197.502":
        a = t.find("(6)"); b = t.find("(8)", a)
        print(t[a:b][:6000])
    else:
        a = t.find("(1)"); print(t[a:a+2500])
