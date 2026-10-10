# Working-agent snapshot (ARYA-20261010-0406-working-count)

Observed 2026-10-10T04:28Z (host clock). Sources: `ps` on the EliteDesk, `var/dispatcher.jsonl` (last event 04:27:20Z, age ~30s), tmux session list. Not taken from ACTIVE_WORK/ALL_AGENTS.

**Observed working total: 2** = 1 active coordinator-side executor + 1 active background worker (deduplicated by PID/session). **Coverage is partial: see UNKNOWN rows. The true total is at least 2, not exactly 2.**

| # | Role | Task / current action | State | Evidence | Age |
|---|------|-----------------------|-------|----------|-----|
| 1 | Coordinator-side executor (Agent 01 automatic pickup session) | ARYA-0406 working-count: writing this snapshot | ACTIVE | this session; `tools/inbox_pickup.py` daemon PID 3332783 up ~140s | live |
| 2 | Background worker, lane 06 (dispatcher-launched) | F-50 implement (medium risk, 80 turns, 3500s timeout) | ACTIVE | `tools/worker.py F-50 --lane 06` PID 3311960 up ~1490s; dispatcher `running: ["06"]` | ~30s |
| 3 | Dispatcher (`tools/dispatcher.py`, PID 3311931) | Scheduling loop; reports "nothing ready for an idle lane" | ACTIVE (infrastructure, not counted as an agent) | dispatcher.jsonl | ~30s |
| 4 | Interactive Agent 01 coordinator (`claude`, PID 2937731, up ~7h) | Unknown. Process exists; its task cannot be read without a transcript | UNKNOWN (not counted) | `ps` only | live process, no task evidence |
| 5 | Agents 02-07 and other lanes (01-05) | No worker process or dispatcher entry seen. A missing process does not prove idle for interactive sessions | UNKNOWN (not counted) | none | n/a |
| 6 | Desktop work | PAUSED_BY_OWNER (preserved) | PAUSED_BY_OWNER | owner pause | n/a |

Not counted: `mbos.cli worker` fixture loop (PID 2470415, data pipeline, not an agent); CAOSCare processes (another project); kernel `kworker` threads.

Caveats: the dispatcher quota reading was stale (110+ min) until 04:27Z, when it showed session 50% / week 6%, under limits. Lane labels and delivered messages were not counted.

Refresh: at the next real task transition (F-50 worker exit or a new worker launch), using the existing receipts.
