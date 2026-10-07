    python -I tools/make_corpus.py tests/fixtures/corpus7d

Writes day0..day6/{ebay,gsa,email,intake/...}/ shaped like each adapter's real input, plus `labels.json`. That file
maps every sighting `source|listing_id` to the PHYSICAL object it describes. Labels are ground truth for scoring F2
only; the pipeline never reads them. Seeded, stdlib-only, byte-stable output.

Scenarios (all ILLUSTRATIVE, hand-designed to stress dedup):
* persistence: most listings re-appear daily (identity), several with price drops (update, not new item)
* overlap: some eBay listings match both search queries the same day (identity)
* relist: an eBay listing ends, and the same seller re-posts the same unit under a NEW itemId days later
  (same physical object → should be ONE Item)
* twins: a dealer lists two identical units at once (two physical objects → must stay TWO Items)
* GSA lots re-polled daily with rising bids; GovDeals alert e-mails repeat lots across days
* service: a customer uses both the web form and a referral; another submits the form twice
