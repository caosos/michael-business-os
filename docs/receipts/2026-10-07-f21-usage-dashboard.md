# Receipt: F-21, usage / agent dashboard (ADR-0014)

- **Date:** 2026-10-07 · **Actor:** Agent 06 (bounded worker) · **Task:** READY_QUEUE `F-21` (A-30 DONE)
- **Effect:** this branch only. A read-only page `/usage`. It launches, approves, spends and contacts nothing (R14: human channel, loopback, Host-checked, no forms).

## Provenance
`mbos.telemetry` (`read`, `verify`, `summarize`) from the pushed mbos head `727931b`, installed from a `build/`-free extraction. Telemetry file: `$MBOS_TELEMETRY_DIR/worker_runs.jsonl` (default `<repo>/var/telemetry`), read only: the directory is never created. Task states: a READY_QUEUE.md copy named by `MBOS_READY_QUEUE_FILE` (UNKNOWN if unset).

## What was built
- `operator_ui/usage_view.py`; route `/usage` and nav link in `server.py`; `tests/conftest.py` profile pin moved to `mbos-727931b`.
- Shows: active (CLAIMED) / queued (READY) / blocked tasks; runs, succeeded/failed, tasks completed, model mix (Sonnet/Opus/Fable/Haiku and any other), average duration, turns, escalations/retries, throughput per day, recent runs; quota 5-hour and weekly % with the snapshot's source and time; Fable weekly % only from a manual snapshot, contributor splits always UNKNOWN (no programmatic source); cost labelled "Claude Code estimate, not a bill".
- No fabricated number: no runs, no readable file, or a missing field shows UNKNOWN, never 0. A failed chain verification or unreadable file shows a loud error banner and **hides every figure**.
- Finding (FACT): the 727931b `summarize` has no `tasks_completed` (added after the pin); the page counts the rows' `task_completed` flag if present, else UNKNOWN.

## Verification (FACT)
- `tests/test_usage_f21.py` (9 tests): fixture file renders all figures and sources; cost label next to the number; empty and missing files all UNKNOWN with nothing created; missing fields UNKNOWN not zero; an edited row shows the error and hides the figures; garbage file reported; hostile text escaped; env var selects the directory; live HTTP page has no form and rejects a bad Host.
- Health: `tools/run_tests.sh` gives 163 passed (reference backend), 31 passed (lane D + lane E), exit 0 and exit 0.
