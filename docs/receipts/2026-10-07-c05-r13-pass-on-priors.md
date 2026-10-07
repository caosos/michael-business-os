# Receipt: C-05, R13 `pass_on_priors` (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-05` (READY_QUEUE @ agent-01 `0d107df`; ruling R13). Claimed at `9b35221`. Code at `6e938d2`.

## Rule implemented
**R13:** "A machine PASS archives an item only when at least one decisive input is evidence-backed (basis FACT)."

- **Decisive inputs** are the input fields behind each failed gate, or behind the composite floor when no gate failed. The mapping lives in `engine._DECISIVE` and is listed in `scorecard.pass_basis.decisive_inputs`.

  | Failed gate | Decisive inputs |
  |---|---|
  | economic gates (EV, $/h floor, min profit) | the cost side and revenue side of the ledger |
  | `max_loss_ok` | buy price, parts, failed-repair salvage |
  | `cash_ok` | ask, buy price, fees, parts, materials |
  | skill / license | `required_skills`, `requires_license_he_lacks` |
  | distance | road miles, trips, and the economic set |

- **Evidence-backed** means an `estimates_meta.assumptions[]` record whose basis is FACT, or one marked `evidence_backed: true` by the estimator. Today the only such marking is the comp median from FACT sold comps, which carries those comps' `provenance_ids`. An input with no assumption record is unattested and does not count.
- **Output:**
  - `scorecard.pass_on_priors`: true only on a PASS with no evidence-backed decisive input
  - `scorecard.pass_basis`: the decisive and backed inputs, for audit
  - an R13 reason line

  The spine routes a flagged PASS to RESEARCHING (A-12).

## Acceptance evidence (FACT)
- **Golden** `examples/mower_no_start.scored.json`: PASS on the $40/h floor with nothing attested → `pass_on_priors: true`.
- **Golden** `examples/project_vehicle_truck_over_cap.scored.json`: cash-cap PASS on an attested (FACT) listing price → `pass_on_priors: false`.
- **Estimator path:** Agent 02's welder with 3 FACT sold comps is a PASS (below the floor). It is **not** flagged, because the resale target is evidence-backed. With asking-only comps, the target is not backed.
- The flag is never set on YES or MAYBE.
- **Suite:** 127 passed, 70 subtests (py3.12 + jsonschema); 127 OK, 6 skipped (py3.10 stdlib).
- **Engine 0.3.0:**
  - goldens regenerated; all 13 verdicts unchanged
  - the truck golden gained one assumption record, so its `inputs_hash` changed
  - the other goldens changed only `engine_version`, the ids it seeds, and the new fields
- `scorecard.schema.json` v1.1.0 documents `pass_on_priors` / `pass_basis`. The change is additive, made before Agent 01 re-vendored the schema.

## Concern raised to Agent 01 (INFERENCE)
- **The literal rule is weak for flips.** "At least one" is satisfied by the FACT asking price on almost every estimated flip, so a floor PASS driven by *prior* repair costs still archives.
- **Stricter variant proposed for the economic gates:** require the revenue side (resale target or quote) **and** at least one cost-side input to be evidence-backed.
- Not implemented: R13 as ruled is what shipped. `pass_basis` exposes everything the spine needs if Agent 01 tightens it.
