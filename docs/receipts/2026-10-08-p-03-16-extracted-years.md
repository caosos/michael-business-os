# P-03-16: extracted model year reaches the KB matcher (DRY-RUN)

- FACT: `build_value_add(..., model_years=)` and `match_hits(..., model_years)` (economics/src/mbos_economics/valueadd.py) accept Agent 02's `[{"year": int, "evidence": str}]` (`mbos_discovery.model_years`, P-02-14/15). Years the title does not already state in four digits are added to the match text; malformed rows are ignored.
- FACT: a year-specific hit shows the year as an INFERENCE quoting the shorthand ("2018 from \"'18\""), keeps the sourced FACT risk (`source` + `provenance_id`); a 2015 or absent year gives no hit and an `omitted` UNKNOWN line. The `value_add_hash` includes the quotes only when given, so existing hashes and goldens are unchanged.
- Tests: `economics/tests/test_p0316_extracted_years.py` (6). Lane suite: 355 passed, 22 skipped, 0 failed.
- UNKNOWN / hand-off: `EconomicsEnricher` lives in `src/mbos/adapters/economics.py` on the coordinator branch (not editable from lane 03). Its `_value_add` must pass `model_years=` (from `mbos_discovery.model_years.extract_model_years(title)`, or `kb_hits(...)["model_years"]`) to `build_value_add`. Card lint was not run in-lane (block shape is unchanged).
- Provenance: 02 @ 349f21c; coordinator adapter read via `git show origin/research/agent-01-coordinator`.
