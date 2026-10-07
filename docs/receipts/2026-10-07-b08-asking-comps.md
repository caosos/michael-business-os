# Receipt — READY_QUEUE B-08: eBay Browse ASKING comps for Agent 03's bundle

- **Date:** 2026-10-07 · **Actor:** Agent 02 (with Agent 03) · **Task source:** READY_QUEUE @ agent-01 `aa88e7a` (B-08).
- **Coordination:**
  - I reported a bug in 03's `comps_feed.entry()`: a KeyError on asking comps. 03 fixed it @ `e1869f2` and added my repro as a regression test.
  - 03 explained the asking-only semantics (round-one §14.1). I adopted 03's fenced assertions in place of my mistaken "insufficient" expectation.
- **External effects:** none. Asking comps are derived from already-retained fixture listings, with no API calls.

## Acceptance: "03's estimator consumes them with the right basis" — MET (FACT)
- `tests/test_b08_asking_comps.py` (4 tests) against Agent 03's engine 0.6.1 @ `e1869f2`:
  - Records are `kind: asking` with `observed_date`, never a `sold_date`. Provenance is FACT/external. Auctions, free and ended listings are excluded, and the subject is never its own comp.
  - Asking-only: estimate `estimated` + `no_sold_comps` gap; no YES (`sold_comps_ok = false`); a PASS ⇒ `pass_on_priors`; research lines are labelled as asks.
  - With SOLD comps added: SCORED, and the asking comp is carried as `asking`.
- Full suite: **146 passed, 0 xfail**.
- Found while installing: 03's branch commits a stale `economics/build/` (0.3.0) that `pip install` packages in place of `src/`. Reported to 03; worked around locally.
