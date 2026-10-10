# Read-only photo access evidence, serial follow-on context

Owner wants actual GSA listing photos. Keep A60 Hide/learning scope separate; no new parallel implementation worker or account integration.

Source review of live eda3eee:
market_view._photo calls landing_fix.photo_tile for EVERY ppms.gov URL, never emits an img request. landing_fix.NO_PHOTO says "Photo is behind GSA's login" unconditionally, based on an earlier401 comment. Adapter retains imageURL from API/cache. Logging into GSA alone cannot change this rendering branch.

Existing recorded fixture tests/fixtures/gsa_live/active-auctions.json on lane02 contains exact trailer image:
https://www.ppms.gov/gw/auction/ppms/api/v1/auction/image/31QSCI27006005.jpg
Original listing https://www.gsaauctions.gov/auctions/preview/378501
Official field documentation lists ImageURL: https://gsa.github.io/auctions_api/fields

Arya's ordinary web open of this exact image returned tool-inaccessible, not an observed401. Existing coordinator, as bounded read-only research in the serial photo follow-on: inspect the stored URL and normal unauthenticated response status/content type/redirect destination. One representative fetch is enough; no inventory refresh, scraping, proxy workaround, credential/session extraction, auth bypass or newaccount access. If401/403, record denial and do not bypass. If ordinary public image succeeds, identify the unconditional-tile rendering defect. If unverified, report access unknown rather than universal login requirement.

Retain verified original-listing fallback. No UI implementation/deploy automatically follows from this research message; return smallest supported next step to the existing coordinator's serial plan. No private owner bids or financial examples.
