# Alabama fixtures - ALL SYNTHETIC

No page or document has been fetched from revenue.alabama.gov by this
repository (the host is egress-blocked from the sandbox and from the
assistant's fetch tool). These files are hand-written to exercise the
parser's CANDIDATE structural assumptions, built only from what a web
search's index showed of the agency's own pages on 2026-09-30 (page
titles, URLs, query-parameter names and text snippets - see
`harvesters/otc/adapters/alabama.py` `ADOR_EVIDENCE`):

- the search page has a county selector named `ador-delinquent-county`
  and a submit parameter `_ador-delinquent-county-submit`;
- the results are searchable by County, CS Number, Parcel Number and the
  name in which the property was assessed when it sold to the State;
- the CS Number is a link that generates an online application; the
  detail page takes `?ador-view-application=<CS number>`;
- one CS-number-shaped value seen was 8 digits with a leading zero.

Everything else here (table markup, header wording, selector values,
every CS number, parcel number and name) is INVENTED for the test and
must not be read as the source's real layout or data. A fixture captured
from the live page replaces these when the source is verified; until
then the `parser_fixture_validated` activation requirement stays unmet.

## `transcript_04_SYNTHETIC.txt` (2026-10-25)

Text lines in the layout of the ADOR weekly county transcript PDFs
(`WWW_TRANS_<NN>.PDF`), as ONE live transcript (file 01) was read
value-free on 2026-10-25: the four-line page header, a record's first
line (name, CO., YR., C/S#, CLASS, CODE, PARCEL ID, description), the
amount line, description continuation lines, a page break between a
record and its amount line, a name printed against the county code with
no space. Every name, C/S#, parcel ID, description and amount here is
INVENTED; nothing from the real transcript is in this repository. It
exercises `harvesters/otc/adapters/alabama_transcripts.py`; it is not a
capture of the live source, so `parser_fixture_validated` stays False.
