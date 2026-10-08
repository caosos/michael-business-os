# Receipt: G-11, adversarial acceptance of the Deal Sniffer product seams (Agent 07, lane G)

- **Task:** G-11 (P1). DRY-RUN only; pure functions, nothing published, contacted or spent. Stack: `mbos` 01 `51dbd51` (A-23 mission, A-25 merchandising, A-26 campaign + valuation), installs verified byte-identical. Examples vendored under `qa/ext/seams/`.
- **Suite:** `qa/tests/seams/test_product_seams.py` (104 cases: 48 controls that must keep passing, 56 strict xfails tied to F-59…F-68). `python -m mbos_qa card` reports 368 passed / 0 failed overall.

## What holds (positive controls)
- Merchandising: price/terms change, extra terms key, basis upgrade, UNKNOWN shown as known, omitted or reworded defect, homoglyph and zero-width tampering of a defect, invented fact, hidden material fact, stale hash, other inventory, "Like new" in the headline, "Runs great" in the CTA, "No smoke", "Inspected by a local shop": all caught. Truthful reordering and rewording passes.
- Mission: over-spend, DO_NOT_SPEND with legs, invented gap for a null target, gap arithmetic, duplicate item, range order, ledger arithmetic, impairment over principal or beside earned capital, negative cash leg, probability > 1: all caught.
- Campaign: autopilot without limits, offer above max price or above total spend, unknown level, negative price, string max_matches, extra keys: caught. Only WATCH_ONLY / RECOMMEND + ACTIVE may run; ASSISTED_DEAL and BOUNDED_AUTOPILOT never run.
- Valuation: `not_an_appraisal` false or missing, range without evidence, low > high, no ranges with medium confidence or no reason, "high" on asking comps only, extra `appraised_value` key, negative low: caught. A home may return all-UNKNOWN.

## Findings (all owner 01)
| ID | Sev | Seam | What slipped (repro = the matching test in `test_product_seams.py`) |
|---|---|---|---|
| F-59 | **P1** | merchandising | 13 euphemisms for a material defect ("Runs when it wants to. Sold as is, minor cosmetic smoke.", "just needs a tune-up", "Does not smoke at idle") and 7 obfuscations (nbsp, double space, zero-width, leet, Cyrillic i) pass the regex lint |
| F-60 | P2 | merchandising | the defect need not appear in the prose (3900-char fluff body passes); label "Ready to Work" / "Quick Turn" on a smoking mower passes |
| F-61 | P2 | merchandising | lowering severity to `minor` in the inventory, or deleting the defect, unlocks "Runs great"; no provenance on severity |
| F-62 | P2 | merchandising | any verified fact (a VIN) unlocks "Inspected and certified. Tested and working."; a view can invent a `provenance_id` |
| F-63 | P2 | mission, campaign, valuation | NaN / Infinity pass every rule (8 cases, incl. NaN autopilot limits and a NaN `available_to_deploy`) |
| F-64 | P2 | mission | null projection with `remaining_gap: 0`; $9,500 projected from legs worth $455 |
| F-65 | P3 | mission | DEPLOY with no legs, HOLD/UNKNOWN that spend, hours exceeded, inverted period, duplicate scorecard, 2020 ledger, DEPLOY under impairment |
| F-66 | P2 | campaign | `may_run` ignores expiry, raises KeyError on `{}`; an autopilot whose limits already expired validates |
| F-67 | P2 | valuation | range order across keys, fake precision (1234..1234), "high" on one bare sold_comp, "medium" on priors only |
| F-68 | P3 | valuation | "Certified appraised value" and "verified and guaranteed by appraiser" in free text; null ranges missing from `unknowns` |

Recommendations are in each finding (`python -m mbos_qa` FINDINGS). The central one for F-59: a deny-list of phrases can never be complete; require the verbatim material defect near the top of the prose and normalise text before matching.
