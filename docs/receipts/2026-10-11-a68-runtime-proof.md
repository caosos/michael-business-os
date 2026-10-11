# A-68 runtime evidence (Agent 01 interactive session, recorded 2026-10-11T03:52:33Z, code a838b5d, repo head 0f5436d)

## Inspected first (existing runtime, nothing created)
- Feed: existing Monitor on `tools/next_work.py --watch 120` (watcher pid 218933, started 2026-10-11T03:51:44Z); the code with the A-68 changes (300 s retry, poll cap 240 s, pause/quota suppression, latency log) was loaded at the earlier re-arm; the log `var/next_work_log.jsonl` is live.
- Owner pause flag: absent. Quota guard: clear (no block reported). Active claims: only this instruction (engineering `begin` at ~03:52Z). No eligible dependency-ready task other than this instruction: A-62 is already DONE (lane 06 cc16e62, verified), A-68 is the task being proved.

## Observed end-to-end handoff (real, one instruction, no fabricated work)
| Step | Time (UTC) | Source |
|---|---|---|
| Instruction ARYA-20261010-2223-a68-live-proof published on the liaison branch | 2026-10-11T03:51:14Z | commit time of the inbox file on origin/liaison/aria-to-agent-01 |
| One actionable notification delivered to the Agent 01 session ("NEW INSTRUCTION ...") | 2026-10-11T03:51:46Z | var/next_work_log.jsonl (kind NEW, within_sla true) and the Monitor event |
| Publish to notification | **32.5 s (<= 300 s)** | difference |
| Engineering claim (STARTED) recorded | about 03:52Z | var/engineering_state.json |
- Dedup: one NEW line for this id; no further line while claimed (log shows a single entry).

## Limits and what is NOT proven (kept separate)
- The 32.5 s includes a fresh watcher start: the watcher process started at 03:51:44Z, two seconds before the notification, so this sample does not isolate the steady-state poll wait. The steady-state bound (first announcement within one poll of at most 120 s, never above 240 s, plus the fetch) is argued from the code and proven only with the fake clock (299 s quiet, 300 s reminder), not measured live.
- The task-completion to next-task path was NOT measured live: no further eligible approved task exists, so there was nothing to hand off after a completion.
- Pickup's own ACK for this message had not appeared on origin at the time of this receipt (separate component: docs ACK is not execution).
- Monitor lifetime: nothing is delivered between a 30-minute expiry and the re-arm; the 300 s bound holds only while the Monitor is armed and the session is open.
- Disposition: A-68 stays PARTIAL (code and tests done; one live instruction handoff observed at 32.5 s; steady-state poll latency and completion-to-next-task handoff unmeasured).
