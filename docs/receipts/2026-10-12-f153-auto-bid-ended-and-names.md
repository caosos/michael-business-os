# F-153: ended auto-detected bids and source display names (lane 06, DRY-RUN)

- Task: F-153 (follow-up to F-152). Provenance: queue row F-153; code `operator_ui/market_autobids.py`.
- Change: an auto-detected My bids row whose latest e-mail event is won/lost/closed shows `ended (per your e-mail, <observed date>)` instead of a `closes in ...` countdown; source key shown as its display name (GovDeals, Public Surplus, GSA Auctions, HiBid). Nothing else changed; no network, no mail touched.
- Tests: `tests/test_market_f152.py` (new `test_f153_ended_rows_and_display_names`; the F-152 wording test now expects the ended text, since all fixture listings end won/lost/closed).
- Agent 01 browser check: NEED.
