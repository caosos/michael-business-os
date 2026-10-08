# Receipt: C-26 estimator categories, listing facts, true status text (DRY-RUN)

Tags: FACT / INFER / REC / UNK. Nothing was sent, spent or contacted.

## Provenance
- FACT: queue row C-26 (agent-01 READY_QUEUE); findings F-106, F-107, F-110 from `docs/qa/MISSION_DRYRUN.md` (agent-07 branch).
- FACT: fixture records copied to `economics/tests/fixtures/training_flips.json` from agent-01 `fixtures/sources/training_examples.json` (illustrative, not real listings).

## What changed
- **F-106** `estimation-priors.json` 2026.10.5: first-class flip priors `consumer_electronics` and `small_goods` (REC: handling hours, parts, sale probability, days to cash, `resale_condition_factor`, buyer collects so no meet trip for electronics). An `other_asset` listing resolves to one of them from a closed title/subcategory vocabulary (`flip_subcategories`, `estimate.prior_category`). The Item category enum is frozen and unchanged. `scope_override_required` stays for `other_asset` with no vocabulary match.
- **F-110** `estimate.py`: ask price is a FACT with the item's source provenance; `expected_buy_price` defaults to the ask (INFER; the `negotiation_factor` column is no longer used by the flip estimator). Inline economics are kept instead of replaced: FACT/INFER-labelled values keep their basis, UNKNOWN-labelled and unlabelled rehab figures are kept as UNK (never evidence); resale prices are never taken inline (comps only). Inline `estimates_meta.evidence` and `repair_scope_known: true` are carried with the source provenance (`skill_fit_high` stays derived).
- **F-107** `comps_feed.gap_text` / `waiting_status` / `scored_status`: each gap code (`scope_override_required`, `thin_comps`, `no_sold_comps`, `repair_scope_unknown`, `transport_unclassified`) states its real blocker; `research_step` now returns `status_text` for SCORED items too.

## Acceptance through `research_step` with only a manual comp (`tests/test_c26_training_through_research.py`)
- TV (`other_asset`): SCORED, YES, cash at risk $43.81 (cap $500).
- Recon: MAYBE; status text and rationale name the unidentified fault (`fault_identified`).
- Mower: PASS, `pass_on_priors` false, `cash_ok` backed by `expected_buy_price` (FACT from the listing).
- Unknown `other_asset` still returns `scope_override_required`.

## Goldens re-baselined (reason: expected buy now equals the ask, and kept inline values)
Regenerated with `scripts/regen_deal_sniffer.py` and `scripts/regen_examples.py`: `examples/deal_sniffer/*` (9 files) and `examples/welder_estimated_from_comps.scored.json`. Test pins updated: `test_estimate` (net 842.86 -> 722.86, walk-away 1234 -> 1242), `test_valueadd` (parts ceiling 505 -> 397), `test_enrich` (max acquisition 964 -> 985). The three training classes (`examples/class_aware/`) are unchanged. Not run (needs the agent-04 archive): `scripts/lane_d_export.py`.

## Health
`cd economics && PYTHONPATH=src:tests python -m pytest tests -q` -> 377 passed, 0 failed, 22 skipped.

## Open (UNK)
- The inline-evidence rule trusts the intake record's own `estimates_meta.evidence` (fixtures, intake forms); a scraped listing carries none. Agent 01/06 should confirm that is the intended trust boundary.
- Estimator version label left at 0.14.0; the priors version (2026.10.5) is what the estimate hash seeds on.
