# D-38 receipt: source registry seed truth (DRY-RUN)

- Task: READY_QUEUE D-38. Fix `config/sources.v1.json` (D-37 `c729a2c`) to match what is connected.
- Changes:
  - Removed placeholder `ar_local_auction_houses`. Added `wooley_auctioneers`, `wilson_auctioneers`, `blackmon_auctions`: states [AR], `site_feed`, `connected`.
  - `policy_ref` points at their receipts: B-26 `docs/receipts/2026-10-12-b26-wooley-source-verification.md`; B-28 `docs/receipts/b28-live-smoke/live-smoke.json`; B-29 `docs/receipts/b29-live-smoke/live-smoke.json`. These live on the coordinator branch (FACT: not on this lane branch); B-28/B-29 have only the live-smoke JSON, no markdown receipt (INFER).
  - Added `trashnothing` (national, api, not_connected; personal-use clause pending written confirmation) and `ar_state_surplus` (AR, alert_email, not_connected). Its policy_ref is the B12 status doc as a placeholder (UNK: no terms reviewed).
  - `site_feed` added to the schema enum (definition in the schema description) and to the DB CHECK via new migration `0032_site_feed_access_mode.sql` (0031 is checksummed, not edited).
  - `gsa` policy_ref changed to `docs/receipts/2026-10-09-gsa-api-smoke.md` (its terms URL moved into the note), because acceptance requires every connected row to cite a receipt.
- Note: a database already seeded from D-37 keeps the stale `ar_local_auction_houses` row (rows are never deleted by design).
- Test: `state/tests/test_source_registry.py` asserts the three connected site_feed rows, the two new rows, and that every connected row has a `docs/receipts/` policy_ref.
