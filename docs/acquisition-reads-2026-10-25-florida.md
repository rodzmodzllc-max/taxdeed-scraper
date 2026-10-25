# Florida Lands Available: acquisition procedures read 2026-10-25, pending capture

Owner's rule (2026-10-25): a property is shown to customers only with a path of acquisition.
These three county procedures were read live on 2026-10-25 from the Clerk's / Tax Collector's own pages,
through a fetch tool that summarizes page text. The evidence table (`data/purchase_path_evidence.csv`)
accepts only verified rows traceable to a `job=evidence` capture run, so these are NOT applied yet.
Each page is in `data/acquisition_candidate_pages.csv`; once a capture run confirms the wording, the row
is added to the evidence table as verified. Earlier capture runs got HTTP 403 (Sarasota) or
script-rendered text (Indian River, St. Lucie), so the owner may instead accept these reads.

| County | Source | Active rows | Path type | Page | What the page says |
|---|---|---|---|---|---|
| Sarasota | fl_laft_realtdm | 12 | quoted_amount | https://www.sarasotaclerk.com/Home-and-Property/Tax-Deeds/List-of-Lands-Available | Properties remain on the list for up to three years and are sold on a first-come, first-served basis. Email the Clerk and Comptroller's Tax Deed Department to inquire about the current cost of purchasing property on the List of Lands Available. Cashier's Check: Make payable to Sarasota Clerk and Comptroller. Wire Transfer: Allow 48 hours for funds availability. Upon receipt of full payment and deed information, the Clerk's Office will issue a Tax Deed and record it in the Official Records. |
| Indian River | fl_laft_html | 2 | quoted_amount | https://indianriverclerk.com/land-available-for-taxes/ | AMOUNTS LISTED ARE NO LONGER THE OPENING BID, YOU MUST CONTACT THE TAX COLLECTOR FOR PURCHASE PRICE 772-226-1338 |
| St. Lucie | fl_laft_stlucie | 3 | phone_mail | https://stlucieclerk.gov/faqs2/online-auctions-faqs | Can I purchase a Lands Available property online? No, Lands Available properties cannot be purchased online. For more information regarding purchasing Lands Available properties or call the Clerk's office at 772-462-1476. |

Contacts recorded on the pages (only those the page attributes to the tax deed / Lands Available office):

- Sarasota: Sarasota County Clerk of the Circuit Court and County Comptroller - Tax Deed Department, TaxDeedClerk@sarasotaclerkandcomptroller.com
- Indian River: Indian River County Tax Collector, 772-226-1338
- St. Lucie: St. Lucie County Clerk of the Circuit Court and Comptroller, 772-462-1476
