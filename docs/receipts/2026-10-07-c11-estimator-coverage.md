# Receipt: C-11, estimator coverage (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-11` (READY_QUEUE @ agent-01 `20d6dc6`). Claimed at `871c994`. Code at `c648ca3` (package 0.7.0, priors 2026.10.3).
- **Scope:** this branch only. Priors 2026.10.2 are archived in `config/history/`, and the scoring config is unchanged.

## Changes
- **Comps vocabularies** now exist for every named flip category:
  - tool (type and brand)
  - compressor (type added to size)
  - commercial equipment, mechanical equipment, project vehicle (type)

  `other_asset` is deliberately empty: an uncategorized asset needs human-chosen comps.
- **`other_asset` and `other_service` priors** are generic, conservative and **gated** by `requires_scope_override`.
  - Without provenance-carrying human overrides for the scope (flip: parts, labor, skills; service: labor, materials, skills), the estimate is `insufficient` with blocking gap `scope_override_required`, and the gap names the missing fields.
  - Scope is never guessed. Previously these categories were refused outright with no path forward.
- **Bug fixed:** scope overrides are now merged into the priors *before* computation (`_prior_view`).
  - Before, an override of `job.labor_hours` replaced the field but the quote stayed computed from the prior hours.
  - Now a 10-hour override raises the drywall quote by the extra 6 hours × $85, and a flip labor override changes the hold days.
- An **unknown category** (not in Item v1) gives an explicit `category_unestimable`.

## Acceptance evidence (FACT)
"Coverage matrix test: 19/19 categories produce either an estimate or an explicit `insufficient` with gaps": `tests/test_coverage.py`, 11 tests and 86 subtests.
- Every flip category has the full prior key set for all 4 conditions and a comps-query entry. Every service category has the full job/quote template.
- Under every bundle (no evidence, 3 sold comps, plus human scope), each of the 19 categories either estimates or returns a **blocking** gap.
- Every estimate scores without error, tags every assumption, and validates against the v1.1.0 economics schemas.

Verdicts below come from synthetic inputs (a $400 ask and the same 3 comps for every category). They prove only that scoring runs; they are not meaningful verdicts.

| Lane | Category | No evidence | + 3 sold comps | + human scope overrides |
|---|---|---|---|---|
| flip | commercial_equipment | insufficient: no_comps | estimated (PASS) | estimated (PASS) |
| flip | compressor | insufficient: no_comps | estimated (MAYBE) | estimated (PASS) |
| flip | generator | insufficient: no_comps | estimated (PASS) | estimated (PASS) |
| flip | mechanical_equipment | insufficient: no_comps | estimated (MAYBE) | estimated (PASS) |
| flip | mower | insufficient: no_comps | estimated (MAYBE) | estimated (MAYBE) |
| flip | other_asset | insufficient: scope_override_required | insufficient: scope_override_required | estimated (PASS) |
| flip | project_vehicle | insufficient: no_comps | estimated (PASS) | estimated (PASS) |
| flip | tool | insufficient: no_comps | estimated (MAYBE) | estimated (MAYBE) |
| flip | trailer | insufficient: no_comps | estimated (PASS) | estimated (PASS) |
| flip | welder | insufficient: no_comps | estimated (MAYBE) | estimated (PASS) |
| service | assembly | estimated (MAYBE) | n/a | estimated (MAYBE) |
| service | drywall_repair | estimated (MAYBE) | n/a | estimated (MAYBE) |
| service | equipment_repair | estimated (MAYBE) | n/a | estimated (MAYBE) |
| service | handyman | estimated (MAYBE) | n/a | estimated (MAYBE) |
| service | mechanical_service | estimated (MAYBE) | n/a | estimated (MAYBE) |
| service | mobile_repair | estimated (MAYBE) | n/a | estimated (MAYBE) |
| service | other_service | insufficient: scope_override_required | n/a | estimated (MAYBE) |
| service | smart_home_install | estimated (MAYBE) | n/a | estimated (MAYBE) |
| service | technical_service | estimated (MAYBE) | n/a | estimated (MAYBE) |

- **Suite:** 175 passed, 159 subtests (py3.12 + jsonschema); 175 OK, 8 skipped (py3.10 stdlib). Goldens regenerated under 0.7.0 with verdicts unchanged (4 YES / 3 MAYBE / 7 PASS).

## Open (UNKNOWN)
- Category priors are REC placeholders until LEARN (C-07) calibrates them from outcomes.
- The `mobile_repair` scope (on-site vs device repair) is still unconfirmed.
