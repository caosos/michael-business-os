# Receipt — READY_QUEUE B-10: discovery acceptance F1–F4 harness

- **Date:** 2026-10-07 · **Actor:** Agent 02 · **Task source:** READY_QUEUE @ agent-01 `c23bee8` (B-10, P1).
- **External effects:** none. Fully offline, synthetic corpus.

## Acceptance: "Harness green; F2 rate reported" — MET (FACT)
- `mbos-discover acceptance --corpus tests/fixtures/corpus7d` exits 0 and reports:
  - F1 PASS (36 Items)
  - **F2 PASS: missed-duplicate rate 0.00% (target < 2%), false merges 0, 36 Items / 36 objects (41 labelled sightings)**
  - F3 PASS (403/429 → 1 L2 request each, then no requests)
  - F4 PASS (8 forbidden sources, 0 touched, 0 forbidden hosts)
- First measurement before the relist rule: F2 = 7.69% (FAIL), caused by 3 relists. That failure was the reason to add the rule.
- Tests: `tests/test_b10_acceptance.py` (8): harness passes, corpus reproducible, CLI exit code, relist rule edge cases, and the **known ambiguity** stated as a test.
- Limitations: the corpus is synthetic (a live 7-day F2 sample needs credentials), and the spine path's relist detection is pending A-14.
