# Receipt — READY_QUEUE B-15 (P0): Deal Sniffer `listing_activity` + `seller` enrichment

- **Date:** 2026-10-07 · **Actor:** Agent 02 · **Task source:** Agent 01 dispatch + READY_QUEUE @ `d2ef52f` (ADR-0011, from Michael's request).
- **Inputs:** `mbos.spine.record_enrichment`, `mbos.card` (`build_card`, `validate_card`, `enrichment_from_item`) and `card.schema.json` @ `d2ef52f` (read-only install; test-only copies of the schema and `operator_profile.v1.json` in `tests/fixtures`).
- **External effects:** none (fixtures, throwaway Postgres).

## Acceptance — MET (FACT), except where marked
- eBay fixtures give real dates and seller feedback: `posted_at` 2026-09-12, `age_days` 24, `rating` 98.6% / 412.
- Craigslist and Marketplace payloads, which are tempting text-laden fixtures, give an empty seller block and no dates.
- "Nothing fabricated" is proven by tests:
  - whitelist only; unknown source → {}
  - first-seen is never an age
  - future dates dropped
  - relist only from two listing ids
  - no stale risk without a date or for auctions
  - no "not a relist" assertion
  - price movement only from our own observations
- The blocks pass the card schema and lint on the real card: `validate_card` → `[]`. The rendered card lists the omitted keys as UNKNOWN.
- Idempotent attach, with no orphan provenance.
- Full suite: **188 passed, 0 skipped**.
- Not verified:
  - The eBay field names against live eBay (docs page returned 403).
  - `spine_d` on lane D's DB.

## Environment finding (not mine; reported)
`/run/user/1001` (tmpfs, 1.5 GB) was **100% full**, mostly from Agent 07's leftover `a07-spine-pg-*` Postgres clusters. That blocked any Postgres start there ("No space left on device"). I did not touch their directories. My test harness now puts its sockets in `/tmp`, and I removed only my own stale dirs.
