# Pickup receipt: ARYA-20261010-2113-heavy-scrap-evidence-gate

## What I did
- Read the instruction from `origin/liaison/aria-to-agent-01`.
- Added section **13b-1 "Heavy scrap / component recovery feasibility gate"** to `docs/product/DEAL_SNIFFER_START_HERE.md`, directly under 13b. It is the canonical doc adoption.
- It covers: the no-bid rule when move cost is unknown; the yard-acceptance or transport/loading/cutting cost requirement; the required evidence list; gross versus net proceeds; no double counting; BLOCKED output listing exact missing evidence; and "why didn't the seller scrap it" as a due-diligence hypothesis.
- No private owner financial examples. A-59/A-60/A-61/A-62 rows in READY_QUEUE.md were not touched.

## Tests
None run (docs-only; 0 code changes, 1 doc section added). No automated implementation is claimed.

## Remaining blockers
- None for the doc. Any implementation (a gate in the valuator) would need a new READY_QUEUE row. None was added because the instruction says no new implementation task.
- No yard contact, bid, purchase or live change was made.
