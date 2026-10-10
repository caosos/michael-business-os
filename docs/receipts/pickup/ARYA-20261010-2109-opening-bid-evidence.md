# Pickup receipt: ARYA-20261010-2109-opening-bid-evidence

Dry-run, docs only. No bid, contact, spend, restart, cache refresh or code change.

## Done
- Read the instruction (origin/liaison/aria-to-agent-01) and the ACK.
- Verified against repo truth: `docs/receipts/2026-10-09-gsa-api-smoke.md` lists the cached GSA fields (highBidAmount, biddersCount, reserve, aucStartDt/EndDt, itemDescURL, ...). FACT: no opening/minimum-bid field is present. The lane02 lot379294 fixture itself is not on this branch (UNK: not re-inspected here); the instruction's values (null / 8 / true) are taken as stated.
- INFER: with the current permitted data a minimum allowed bid cannot be verified; the only honest display is "Opening/minimum bid unknown — check original listing" with the link.
- Added READY_QUEUE row **A-62** (P2, BLOCKED on A-60, CODE lane, existing 01 engineering session) with the smallest bounded scope and acceptance test.

## Tests
None run (docs-only; 0 code changes). A-62 carries its own acceptance test.

## Remaining blockers / owner decisions
- A-62 implementation waits for A-60 acceptance. No owner decision needed unless Michael wants an authorised original-listing fetch (not authorised here).
- Yard pickup value, fees, towing, title etc. remain UNKNOWN.
