# Arkansas fixtures - ALL SYNTHETIC

No page has been fetched from cosl.org by this repository (egress-blocked
from the sandbox and from the assistant's fetch tool). These files are
hand-written to exercise the parser's CANDIDATE assumptions, built only
from what a web search's index showed on 2026-09-30 (see
`harvesters/otc/adapters/arkansas.py` `COSL_EVIDENCE`): a per-county
"Post Auction Sales List" page reached with `?county=<NAME>` (one value,
DALLAS, observed), entries with a parcel number, a legal description that
describes acreage, and the delinquent tax owed which "represents the
minimum bid". The table markup, the header wording and every value here
are INVENTED for the test. A page saved from the live site replaces these
when the source is verified.
