# Receipt: F-18, the Weekly Mission page

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-18` (P1, unblocked by A-23; claimed in `5bf4304`)
- **Effect:** this branch only. A read-only page: no forms, no writes, nothing is spent or committed.

## Provenance
`mission.schema.json`, `examples/mission/*` and `mbos.mission` (`plan_errors`, `validate_plan`) @ `9cf6f00`, vendored byte-identical (schema + three examples; `card.schema.json` re-vendored). Product direction: `docs/product/DEAL_SNIFFER_START_HERE.md`, ADR-0012/0013.

## What was built
- `/mission` renders a plan document from a local file (`MBOS_MISSION_PLAN_FILE`, as there is no spine producer yet), validated with `mbos.mission.plan_errors` (schema, ledger arithmetic, spend cap, `DO_NOT_SPEND` implies zero cash, gap rule). **A plan that fails validation is not rendered as numbers**; its errors are listed.
- Shows: week, target, hours; **recommendation**; realized so far, projected week (low, likely, high), remaining gap and confidence; the five-field **capital position** (plus principal impairment when present); **best next opportunities** (class, cash at risk, expected net range, days to cash, chance, hours, why); replace-if-stale items; the plan's own UNKNOWN list and explanation.
- **UNKNOWN stays UNKNOWN**: a null target or hours is UNKNOWN, `remaining_gap` stays UNKNOWN (no gap is computed), and a mission with no plan says "No plan yet".
- **DO_NOT_SPEND is shown plainly, first**, as a red banner above the mission.
- **Every leg links to its card** (`/item/<id>`); a leg whose item is not in this store is flagged "unverified". Legs keep the plan's order: no sorting by profit (ADR-0012).

## Verification (FACT)
- `tests/test_mission_f18.py` (12 tests): the A-23 example renders every asked-for field; null target and hours render UNKNOWN; a gap without a target is refused as invalid; DO_NOT_SPEND shown first and invalid if it commits cash; a broken ledger is not rendered; missing and malformed files reported; hostile text escaped; the live page links a real card and has no forms; Host-guarded.
- Mutation check: moving the banner below the mission header fails the DO_NOT_SPEND test; file restored.
- Reference 145 passed; lane D/E 31 passed.

## Note
There is no producer of plans yet (the planner that builds legs from live cards, and the mission/ledger stores, are not in the queue). The page is ready for one: a plan file or, later, a spine reader.
