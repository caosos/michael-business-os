# Receipt: E-19, jurisdiction pack format and evaluator (Agent 05)

- **Date:** 2026-10-07
- **Task:** E-19 (P2; ADR-0013 §8)
- **External effects:** none.
- **Capabilities granted:** none.
- **Legal facts asserted:** none.

## Built
`policy/jurisdiction/` (rules, pack schema, 8 synthetic sample packs), `src/mbos_governance/jurisdiction.py`, `mbos-gov jurisdiction check|eligibility`, and the design doc `docs/integration/05-jurisdiction-packs.md`.

## Verification (FACT)
- 31 E-19 tests pass; the full suite (550 tests) passes on PG16.
- A missing pack or chain, a missing threshold field, a conflict, an unresolved pack and an expired pack are all UNKNOWN, never "no licence needed".
- A stale `date_verified` lowers confidence (0.9 → 0.63 → 0.36). A very old pack is EXPIRED_PACK.
- A "no credential required" finding is cleared only when it is fresh, confident and fully resolved. A credential requirement survives low confidence.
- The most specific pack wins. An unincorporated chain does not inherit a city rule.
- A provider's claim counts only if it passes E-18 validation, is unexpired, and was checked in a jurisdiction on the job's chain.
- The evaluator's source contains no hard-coded local assumption (checked by an AST scan).
- Sample results are never authoritative (`gate` → `ask_michael`).
