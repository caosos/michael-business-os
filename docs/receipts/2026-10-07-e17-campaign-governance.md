# Receipt: E-17, governance for campaigns (Agent 05)

- **Date:** 2026-10-07
- **Task:** E-17 (P1; ADR-0013 §9; unblocked by A-26 @ `c18cabc`)
- **External effects:** none.
- **Capabilities granted:** none.

## Built
- Policy `2026.10.07-w1.10`, `campaigns` block: autonomy → governance, plus an unknown-level rule. The schema pins it.
- `campaigns.decide_campaign()` is a pure, fail-closed decision. `propose(..., campaign=)` applies it and taints the request.
- `spine_adapter.campaign_decision()` gives Agent 01's engine a plain-JSON check.
- Vendored `campaign.schema.json` (sha-pinned), and the design doc `docs/integration/05-campaign-governance.md`.

## Verification (FACT)
- 48 E-17 tests pass, and the full suite (598 tests) passes on PG16.
- `WATCH_ONLY` and `RECOMMEND` request no action. `BOUNDED_AUTOPILOT` is denied with `AUTOPILOT_NOT_AUTHORIZED` even with valid limits. An unknown or malformed level is denied.
- `ASSISTED_DEAL`:
  - drafts only `offer.*` and `comms.*`
  - is denied for purchase, publish, payment, commitment and price changes
  - is denied above the campaign's max price
  - requires step-up, and a YES without step-up is refused
  - executes dry-run only after a YES
- Policy data that loosens any of these makes the policy unavailable. A missing block does the same.
- **No campaign-sourced path skips approval:** a rejected request cannot be approved, the gateway role cannot approve (database privilege), and `auto_approved` is unreachable.
