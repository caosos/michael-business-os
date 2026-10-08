# ACK: ARIA-20261007-1945-agent-runtime-efficiency-and-metrics

- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARIA-20261007-1945-agent-runtime-efficiency-and-metrics.md`
- **Classification:** OWNER_INPUT + TASK_REQUEST + RESEARCH_SUMMARY
- **Disposition:** **INCORPORATED** (ADR-0014) and **TASKED** (remaining items below)
- **Acked by:** Agent 01, 2026-10-08
- **Authority check:** runtime/observability direction only. Every external-action boundary is unchanged: DRY-RUN, no spend, no contact, no publishing. The one mutation outside the repo is a guard in `~/bin/mbos-tmux` (backup `mbos-tmux.backup-20261008`) that refuses to start lanes 02-07 as persistent sessions unless `MBOS_ALLOW_PERSISTENT=1`.

## Disposition by required action
| # | Required | Status |
|---|---|---|
| 1 | Acknowledge durably | this file |
| 2 | Migration plan and READY tasks | ADR-0014; tasks A-28, A-29, A-30 (done), A-31, F-21 |
| 3 | Close out Agents 02-06 safely | **Done for 02, 03, 04, 05, 06 and 07.** Each pushed `docs/handoff/LANE_NN.md` and `State: CLOSED`; I independently verified pushed head == worktree head, clean `git status`, handoff present, then closed the tmux session. No worktree or branch was deleted. 07 finished G-10/G-11 first. All six specialist tmux sessions are closed; only `mbos-agent-01` remains |
| 4 | Preserve Agent 01; decide QA | Agent 01 persistent. **QA is not persistent** (value = independence + `qa/` harness, not chat memory). 07 finishes G-10/G-11, closes out, then QA runs as a fresh worker per release window |
| 5 | Bounded-worker launcher on supported non-interactive mode | `tools/worker.py` (`claude -p --output-format stream-json --verbose`) |
| 6 | Model router + receipts | `config/model_router.v1.json` (data) + `mbos.router`; every run records rule id and reason in telemetry |
| 7 | Telemetry in the Operator UI | `mbos.telemetry` (hash-chained JSONL) + **F-21** dashboard (executed by the first bounded worker) |
| 8 | Supported access to Max quota percentages | **Investigated and verified.** Claude Code's documented stream-json emits `rate_limit_event` with `unifiedWindows.five_hour` and `seven_day` `{utilization, resetsAt}`. A one-turn probe returned 83% / 39%, consistent with Michael's reading. Captured automatically on every worker run. **Not available programmatically:** per-model weekly % (Fable), the ">150k context" and "4+ parallel sessions" splits, a status-line/CLI/file/OTel export. Those are UNKNOWN or manual snapshots. No private endpoint was touched |
| 9 | Amend START_HERE / COORDINATION / launcher / runbooks | START_HERE, COORDINATION, RUNBOOK, `docs/runbooks/AGENT_RUNTIME.md`, `docs/handoff/CLOSEOUT_CHECKLIST.md`, `mbos-tmux` guard |
| 10 | DRY-RUN boundaries unchanged | unchanged; the worker prompt repeats them and denies network tools, sudo, force-push |

## Honest notes
- `total_cost_usd` is stored as `cost_estimate_usd` with `cost_is_estimate_not_a_bill: true`; under Max it is not a separate bill.
- The probe cost one tiny call; the quota percentages appear on every worker run, so no separate sampling call is needed.

## Acceptance evidence (all from `var/telemetry/worker_runs.jsonl`, hash-chain verified)
- **F-21 (lane 06, usage dashboard)** completed by a fresh Sonnet worker: 53 turns, 523 s, est. $0.86, commit `da87d26`, independently verified by Agent 01 (pushed; 163 + 31 tests pass; lane identity).
- **C-23 (lane 03)** completed by a fresh Sonnet worker in `auto` permission mode: 22 turns, 0 permission denials, est. $0.36, commit `3eb358f`.
- **G-12 (lane 07, fresh QA worker, Opus)**: see READY_QUEUE.
- Release gate with all of this: 415 passed, installed lane packages identical to pushed heads (gate output in `docs/status/RELEASE_GATE.md`).

## What the first runs taught (fixed, with tests)
1. **Exit 0 is not success.** The first F-21 attempt exited cleanly having done nothing. Telemetry `task_completed` now requires the worker's own DONE report AND a new commit.
2. **Lane branches do not contain the coordination files** (START_HERE etc. live on Agent 01's branch). Workers now read them via `git show origin/research/agent-01-coordinator:<path>`.
3. **Pattern allowlists cannot cover real shell work.** Two attempts were blocked by permission denials. Workers now default to `--permission-mode auto` with the deny-list kept; `bypassPermissions` is refused by the launcher.
4. **A stronger model cannot fix a permissions problem.** Escalation is skipped for permission denials and for a worker-reported BLOCKED.
5. **Quota guard**: the 5-hour window read 89% during this migration (Claude Code's own `rate_limit_event`), so launches now pause above 90% session / 90% weekly on a fresh supported reading (`--ignore-quota` overrides, recorded). Stale or missing readings never block.

## Owner note (not a blocker)
Per-model weekly Fable % and the contributor splits (>150k context, 4+ parallel sessions) still have no supported programmatic source. Michael can enter a manual snapshot; the dashboard shows them as UNKNOWN until then. The Fable pool stays unused by design until a `--long-horizon` architecture/migration task exists.
