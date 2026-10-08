# ADR-0014: Bounded workers, model routing and usage telemetry (replaces persistent specialist sessions)

- **Status:** ACCEPTED. **Source:** Aria ARIA-20261007-1945 (Michael's runtime/efficiency direction). **Authority:** runtime/observability only; every external-action boundary is unchanged (DRY-RUN).

## Problem (FACT, from Michael's Claude Usage screen, 2026-10-07)
91% of usage was at >150k context; 89% happened while 4+ sessions ran in parallel; 21% came from subagent-heavy sessions; session window 75%, week 38%, Fable 0%. Seven long-lived conversations that accumulate context burn Max capacity and are not needed: all durable knowledge already lives in git (repo truth, receipts, handoffs).

## Decision
1. **Persistent control plane = Agent 01 only.** QA (07) is **not** persistent: its value is independence and the `qa/` harness, not chat memory. QA runs as a fresh worker per release window (re-run command in `docs/handoff/LANE_07.md`). The launcher still lets a human override this deliberately (`MBOS_ALLOW_PERSISTENT=1`).
2. **Lanes 02-07 run as fresh bounded workers**: one `claude -p` run per task, started from repo truth (`tools/worker.py`): START_HERE, the Deal Sniffer onboarding doc, COORDINATION, the lane's `docs/handoff/LANE_NN.md`, the task row. The worker claims, implements, tests, writes a receipt, commits with the lane identity, pushes its lane branch, prints a final JSON line and exits. Resume an old session only when its private context is genuinely valuable and still compact.
3. **No termination before durability.** A session is closed only after its closeout (`docs/handoff/CLOSEOUT_CHECKLIST.md`) is pushed and Agent 01 has independently verified: pushed head equals worktree head, `git status` clean, handoff present, `State: CLOSED`. No worktree or branch is deleted.
4. **Model router is data** (`config/model_router.v1.json`, `mbos.router`). Aliases only (`sonnet`, `opus`, `fable`, `haiku`), resolved by the installed CLI; no model ids are hard-coded.
   - Sonnet: default (implementation, tests, adapters, docs, bounded research).
   - Opus: planning, cross-lane integration, high-risk review, and a bug that already beat a cheaper attempt.
   - Fable: only `long_horizon` architecture / migration / synthesis / deep research. Never routine work, never an automatic escalation for non-long-horizon tasks.
   - Haiku: low-risk classification/extraction, falling back to Sonnet when unavailable.
   - One escalation per task (Sonnet -> Opus; Opus -> Fable only if long_horizon).
5. **Telemetry** is an append-only hash-chained JSONL (`var/telemetry/worker_runs.jsonl`, `mbos.telemetry`) of supported Claude Code output only: session_id, models used, duration, API duration, turns, token counts, `total_cost_usd` (stored as `cost_estimate_usd`, flagged as an estimate: **not a separate bill under Max**), success/error, retries, escalations, routing rule and reason, head before/after.
6. **Quota percentages (investigated 2026-10-08).** FACT, verified by a real one-turn probe: Claude Code's documented `--output-format stream-json --verbose` emits a `rate_limit_event` with `unifiedWindows.five_hour` and `seven_day` `{utilization 0..1, resetsAt}` for Max/OAuth auth. The worker records these automatically (`quota_from_rate_limit`). **No supported source exists for per-model weekly limits (Fable %), the ">150k context" or "4+ parallel sessions" contributor splits, or a status-line/CLI/file/OTel export**; those stay UNKNOWN unless Michael enters a manual snapshot (`quota_snapshot`). Nothing scrapes an undocumented endpoint or touches credentials.
7. **Efficiency policy**: fresh worker by default; avoid >150k context; `/compact` only when continuing a justified context, `/clear` when switching task; at most 2 heavyweight workers in parallel unless independence is proven; subagents for isolated parallel work only; measure output per usage window, not agent count.

## Consequences
- `tools/worker.py`, `mbos.router`, `mbos.telemetry`, `config/model_router.v1.json`, runbook `docs/runbooks/AGENT_RUNTIME.md`.
- Operator UI usage dashboard is task F-21 (executed by the first real bounded worker, the migration's acceptance test).
- `mbos-tmux` refuses lanes 02-07 unless overridden (host script; backup kept). Stale queue / idle detection is `tools/foreman.py`.
- Supersedes the "seven persistent sessions" assumption in COORDINATION and the launcher.
