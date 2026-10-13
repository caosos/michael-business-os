# Marketplace density and source propagation

- **Requested by:** Michael, 2026-10-13.
- **Source revision:** loaded EliteDesk revision `0278762675e38a94eb8407e1c639ae13b8d718e2`.
- **Change:** Marketplace pages now render up to 50 listings. Existing Previous/page/Next controls remain above and below the grid and show the exact page/total range.
- **Layout cause:** the screenshot's blank right column was not CSS clipping. The 24-card slice ended after six four-column rows while the filter rail continued.
- **GSA:** a release now invokes the existing official read-only GSA adapter explicitly, with its one-request/cache guard, and records cache path, request count, nearby-state record count, as-of, total file count and error. Page GET remains cache-only and never hides a network call. A zero-match GSA row under a narrow distance search offers a truthful 150-mile GSA search.
- **Named local sources:** reviewed offers may use all Marketplace categories. A registered vendor's approved card now answers both its named source selector (for example Half Off Wholesale) and the `Authorized local deals` provenance group; facet counts include both without duplicating the card.
- **Truth boundary:** GovDeals remains not connected until a genuine saved-search mailbox feed exists. eBay remains not connected without official API credentials. HiBid lot reads remain blocked; Nahlen and unapproved local-vendor entries remain manual. No fixture or registry row was converted into a listing.
- **Verification before commit:** `test_market_source_labels.py` + `test_vendor_deal_marketplace.py`: 7 passed. Affected combined group: 36 passed, with the same pre-existing `test_category_counts_equal_filtered_rows` failure reproduced unchanged at base revision `02787626`. Focused 50-card pager assertions and Python compilation passed; workflow YAML parsed successfully; `git diff --check` passed.
- **EliteDesk:** deployment and host/browser proof are pending the manifest commit and self-hosted runner. Do not claim live until that run succeeds.
