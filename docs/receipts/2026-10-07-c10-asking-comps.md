# Receipt: C-10, asking comps crash `build_comps_bundle` (Agent 03)

- **Task:** `C-10` (READY_QUEUE @ agent-01 `c23bee8`).
- **Fixed at `e1869f2`** (package 0.6.1). The fix **predates the queue entry**: Agent 02 reported the bug to Agent 03 directly with a repro, and Agent 03 fixed it right away because it blocked B-08. Recorded here so the queue and status agree.

## The fix
- `comps_feed.build_comps_bundle` no longer reads `sold_date` on kind=asking comps. Bundle entries and the sort key use `observed_date`, and an ask never carries a `sold_date`.
- The estimator emits FACT "asking comp $X on <observed_date>" research lines.
- Agent 02's exact repro is now a regression test (`tests/test_comps_feed.py::TestAskingComps`).

## Acceptance (FACT, reported by Agent 02)
B-08 is green against `e1869f2`. Agent 02 also adopted the fenced asking-only assertions, which do not change C-01's design: estimated with a `no_sold_comps` gap, never YES, and any PASS is R13-flagged.

## Related fix found during this work (`4a93582`)
`economics/build/` (stale 0.3.0 code) had been committed in `1044ed5`. A `git archive` install therefore shipped old code under 0.6.1 metadata (reported by Agent 02).
- The directory is now untracked and ignored, and a test guards against it.
- Verified: an archive of HEAD has no `build/`, and installs as 0.6.1.
