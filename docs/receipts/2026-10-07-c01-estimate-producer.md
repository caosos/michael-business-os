# Receipt: C-01, RESEARCH/estimate producer (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-01` (READY_QUEUE @ agent-01 `99e9ec0`). Claimed at `b923852`, protocol form at `ae2f926`. Done at `42fed5e`.
- **Scope:** code and data on `research/agent-03-economics` only.
  - DRY-RUN; nothing external was contacted.
  - No other branch or worktree was modified. Agent 02's code was exported read-only with `git archive` into the session scratchpad.

## Inputs (provenance)
| Input | Ref |
|---|---|
| Assignment + acceptance | `origin/research/agent-01-coordinator` @ `99e9ec0`: `READY_QUEUE.md` C-01, `COORDINATION.md`, `ROUND_TWO_INTEGRATION.md` §3C |
| Item shape actually produced by discovery | `origin/research/agent-02-opportunity` @ `7b4d9a8`. Pipeline run in fixture mode yielded 10 Items, saved as `economics/tests/fixtures/agent02/items.json` (see the PROVENANCE.md next to it) |
| Scoring engine | this branch, `mbos_economics` 0.1.0, config 2026.10.1 |

## Outputs
- `economics/src/mbos_economics/estimate.py`: `estimate_item`, `apply_estimate`, `load_priors`, `BundleError`.
- `economics/config/estimation-priors.json`: priors 2026.10.0 (REC/UNK). Includes the home base, a town road-mile table (INFER, approximate) and Agent 02 geo_tier fallbacks.
- CLI: `python -m mbos_economics estimate ITEM.json --as-of T [--bundle B.json]`.
- `economics/tests/test_estimate.py` (19 tests) and `economics/tests/fixtures/agent02/`.

## Acceptance evidence (FACT)
"An Item from 02's fixtures gets valid economics and scores past MAYBE-for-missing-inputs":
- **Agent 02's Conway 6x12 trailer** (no economics as discovered), with a 4-sold-comp bundle:
  - estimated
  - the patched Item validates against Item v1
  - scores **MAYBE**: net $842.86, confidence 0.30. The engine names the 4 evidence items that would lift it.
  - With evidence and a provenance-carrying override it scores **YES**, walk-away $1,234. Replay matches.
- **All 4 of 02's service leads:** estimated, valid Item v1, real verdicts (MAYBE). Every one clears the $40/h floor.
- **Flips without comps:** `insufficient`, blocking gap `no_comps`. The resale price is never guessed.
- **02's injection-flagged "brass lamp" (`other_asset`):** refused (`category_unestimable`).
- **Results:**
  - pytest (py3.12 + jsonschema): **94 passed, 54 subtests passed**
  - stdlib unittest (py3.10): **94 OK, 4 skipped** (no jsonschema)

## Design decisions (INFERENCE / RECOMMENDATION)
- **Structured fields only.** Title and description are never read. A test proves injected text does not change any number.
- **Evidence and overrides need provenance.** The estimator never sets an evidence flag itself. `skill_fit_high` is rejected (the engine derives it).
- **Whole-job service quote.** The first draft priced only hands-on hours, and every small lead failed the $40/h floor. A price must also cover travel, admin and quoting time; the corrected quote does.

## Open items (UNKNOWN)
- `quote_rate_per_hour` ($85) and `min_charge` ($125) are pricing-policy placeholders that Michael needs to set (flagged in AGENT_STATUS).
- Town road miles are approximate (INFER). Correct them through a priors bump.
- Without a sold-comps feed, every real flip from eBay Browse stays `insufficient`. Proposed as a task (AGENT_STATUS "Proposed tasks").
