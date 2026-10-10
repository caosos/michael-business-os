# Pickup receipt: ARYA-20261010-2117-a61-full-assessment-record

## What I did
- Extended canonical section 13c of `docs/product/DEAL_SNIFFER_START_HERE.md` with three bullets: full private listing-linked assessment case (evidence + rationale summary, owner estimates vs verified facts, per-item vs category), proposal-first behavior (no autonomous bid/buy/contact), storage honesty (no misuse of acquisition/attestation fields; "learned" only after authorised local write + readback under the correct listingID).
- Amended the existing **A-61** row in `docs/status/READY_QUEUE.md`: inspection must report the exact existing protected write/import/readback route for a complete case, or the minimal missing capability, with the read-only hints from the instruction. No new row/worker/datastore; A-59/A-60 and serial scope untouched.

## Tests
None run (docs-only; 0 code changes). The capability is NOT implemented; I did not independently verify the 300-char/allowed-keys claims (taken from the instruction; A-61 will confirm).

## Remaining blockers
- A-61 still waits on A-60 acceptance. The private case itself stays with the parent; no case values written here. No bid, contact, spend, restart or credentials involved.
