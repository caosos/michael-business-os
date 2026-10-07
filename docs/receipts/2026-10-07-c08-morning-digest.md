# Receipt: C-08, morning digest (Agent 03; Agent 06 renders)

- **Date:** 2026-10-07
- **Task:** `C-08` (READY_QUEUE @ agent-01 `71adb0d`). Claimed at `b582645`. Code at `a81a989` (package 0.6.0).
- **Scope:** this branch only. The function is pure: it writes nothing and reads no clock.

## What it is
`mbos_economics.digest.build_digest(items, as_of, horizon_hours=72, limit=None)` ranks open, scored Item v1 documents into a "what to do first" list. `render_text()` and `python -m mbos_economics digest ITEMS.json --as-of T --text` give the plain-text daily 72-hour plan.

**Ordering** (lexicographic, each step explainable):
1. Bucket: YES + alert → YES → MAYBE (research) → PASS flagged `pass_on_priors` (R13: research before discarding).
2. Inside a bucket, items with a deadline (`recommendation.expires_at` or `normalized.ends_at`) inside the horizon come first, soonest first.
3. Then the value of Michael's hour, **EV $/h × confidence**, highest first.
4. Then time-to-cash, shortest first; then `item_id`.

**Each row** carries:
- a one-line `reason`
- a concrete `action`:
  - YES: an offer ceiling or "send quote"
  - MAYBE: the cheapest decisive evidence, the negotiate-to price, the re-quote floor, or the named YES blockers
  - R13 PASS: the failed gates
- the `window` (<24h / <72h / later)
- `refs`: `scorecard_id`, `inputs_hash`, `recommendation_id`, `provenance_id`

**Excluded items** are listed with a reason, never dropped silently: an evidence-backed PASS (archive), a passed deadline, a decided or closed state, or not scored yet.

The digest has its own Provenance v1 record, derived from every listed recommendation's provenance. `title` is listing text, so Agent 06 must escape it when rendering.

## Acceptance evidence (FACT)
"Deterministic ranking over the goldens + 02 fixtures; explanation per row":
- **Corpus:** the 14 goldens plus the 10 Agent 02 fixture Items. The 4 service leads are scored through C-01; the 6 flips without comps stay unscored.
- **Result:** 17 rows (2 alert, 2 act, 7 research, 6 R13-research) and 7 exclusions (1 evidence-backed truck PASS, 6 unscored 02 flips).
- **Fixed order of the top 5:**
  1. smart-home install (alert)
  2. trailer at $225 (alert)
  3. project vehicle, offer ≤ $1,061
  4. drywall
  5. trailer at $250, negotiate to $227
- **Identical output** (`digest_hash`) under 5 random input shuffles.
- **Every row** has a reason, an action and resolvable refs.
- **Deadline tests:** a 12 h deadline puts the project vehicle at rank 3 in the `<24h` window. A 48 h deadline lifts drywall above a higher-value YES. A deadline beyond 72 h does not change the order. A past deadline excludes the item.
- **Suite:** 154 passed, 73 subtests (py3.12 + jsonschema); 154 OK, 8 skipped (py3.10).
