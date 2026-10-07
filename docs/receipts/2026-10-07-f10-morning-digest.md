# Receipt: F-10, morning digest page

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-10` (READY after C-08; claimed in `185f908`)
- **Intent:** render lane C's ranked "what to do first" list in the Operator UI, with reasons and provenance links.
- **Effect:** this branch only. Read-only pages (`/digest`, `/provenance/<id>`). No writes, no sends.

## Provenance
| Input | Ref |
|---|---|
| Ranking | Agent 03 C-08 `mbos_economics.digest.build_digest` @ `a81a989` (git archive of `economics/`, installed into `.venv`, not merged). The config is packaged in the wheel at this commit |
| Spine | `mbos` @ `c23bee8`; real engine wired in tests via `mbos.adapters.economics.EconomicsEngineScorer()` |

## What was built
- `operator_ui/digest.py`: selects open Items (read-only) and calls `build_digest`. **It never re-orders lane C's ranking.**
  - It pre-checks each item for a lane-C engine scorecard. Other scorecards (e.g. the spine placeholder) are listed under **Not ranked** with a reason, alongside lane C's own exclusions.
  - A missing package or a `build_digest` failure is shown as an error, never a guessed ranking.
- `/digest` shows: rank, bucket (ACT NOW / Decide / Research / R13 research), lane, **escaped** title linked to the open card, lane C's action and reason, deadline window, value $/h, and refs (scorecard_id, inputs_hash, rec_, and a prov_ link). It also shows the digest hash and lane C's digest provenance (tool, version, basis).
- `/provenance/<id>`: a read-only view of any provenance row (kind, basis, actor, what, JSON).

## Verification (FACT)
- `tests/test_operator_ui_f10.py` (5 tests) uses the **real lane C engine** inside the real DBOS workflow on 4 fixtures:
  - The page order equals `build_digest` called directly on the same items, with the same `digest_hash`. Card and provenance links resolve.
  - Placeholder-scored items are listed, not ranked.
  - A `<script>` title is escaped.
  - A missing engine or an engine exception is reported.
  - The pages are read-only and Host-guarded.
- Mutation check: removing the pre-check fails `test_placeholder_scored_items_are_listed_not_ranked`. The file was restored.
- Full suite: `101 passed`.

## Note for Agent 01
At `a81a989`, `mbos_economics` ships its config inside the package, so `EconomicsEngineScorer()` works with no `config_dir`. The adapter docstring (which says the wheel lacks config) is outdated for this version.
