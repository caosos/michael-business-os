# Receipt — READY_QUEUE B-06: IMAP saved-search alert ingestor (tier 2)

- **Date:** 2026-10-07 · **Actor:** Agent 02 · **Task source:** READY_QUEUE @ agent-01 `aa88e7a` (B-06).
- **External effects:** none. No mailbox was opened. IMAP was exercised only through an in-memory fake that implements read commands alone.

## Acceptance: "Fixture emails → RawListing; no network in tests" — MET (FACT)
- `tests/test_b06_email_alerts.py`, 9 tests:
  - GovDeals alert → 2 Items (trailer `auction_current` $350; mower `starting_bid` $500). Off-domain and unsubscribe links are ignored.
  - A spoofed GovDeals alert (dkim=fail, carrying an injection) is quarantined with raw retained. No Item is created.
  - PublicSurplus welder.
  - EstateSales.NET sale event → `other_asset` / `estate sale` / `needs_review`.
  - A newsletter from a foreign sender is never read into storage.
  - Replay from `raw_ref`; repeat runs are idempotent.
  - The IMAP reader is gated on `live` and a password, and uses only login/select(readonly)/search/fetch(BODY.PEEK[])/logout.
  - Spine seam: email alerts → `RawListing` via `discovery_components`.
- Full suite green (see commit message).
