# Delivery gap: GitHub pickup vs the interactive engineering session (A-63)

## Diagnosis (from source and the live registry, 2026-10-10)
1. **Pickup cannot execute engineering work by design.** `tools/inbox_pickup.py` fetches, ACKs, answers PING, and runs a bounded docs-only `claude -p` executor in a side worktree. Live restarts, code and the interactive session are out of its reach; a docs completion is not engineering execution.
2. **An interactive Claude session only runs when text reaches its prompt.** Nothing in pickup or the watchdog can do that without typing into the terminal.
3. **The watchdog cannot see this session.** `~/.claude/sessions/2937731.json` says `cwd=/home/michaelos`, `entrypoint=cli`, `kind=interactive`, `tmux=None` (an ssh login, not tmux). `coordinator_watch.my_session()` requires `cwd` under the worktree, so `status.json` reports "no live Claude session (awaiting connection)" while the session is alive. Even if matched, there is no tmux pane to type into, and `mode.json` keeps tmux wake OFF (owner approval required; classifier denied it 2026-10-09).
4. **Completion never chose the next task.** After one task the session stopped until someone pasted the next instruction.

## Repair within existing permissions (no new watchdog, credential, install, tmux typing or quota bypass)
- `tools/next_work.py` (read-only; `git fetch` only): prints ONE line per NEW inbox instruction or READY queue row that is Agent 01's with dependencies met. Watched by the session itself with the `Monitor` tool (`--watch 120`); each line returns to the same session as a notification. Monitors last at most 30 minutes, so the session re-arms on expiry; when the session is closed there is no delivery (truthful limit).
- `tools/engineering_session.py begin|finish`: idempotent engineering START/DONE with a receipt (`docs/receipts/engineering/<ID>.md`) naming the interactive session pid/entrypoint (not pickup). `begin` on a finished id = `DUPLICATE_IGNORED`; on an unfinished id after restart/re-entry = `RESUME` (one START only). `finish` reports the next eligible approved task (priority, deps met, Done history honoured) and repeats the same answer on a second call (no double advance).
- Pickup: `Type: ENGINEERING_PROOF` is ACKed ("AWAITING the interactive engineering session"), never executed or completed by pickup; its record becomes COMPLETED only when the engineering session sets the ack Stage to COMPLETED on origin.
- Instruction-ID dedup and the ACK -> START -> result states are unchanged.

## Sustained progression (A-65 correction of the one-shot feed)
- **Notified is not claimed.** `next_work.py` keeps `{first, last, count}` per instruction/row in `var/next_work_seen.json` and announces an item as `NEW`, then as `REMINDER #n` every 600 s while it is still eligible and unclaimed. Claimed = `engineering_session begin` recorded STARTED/DONE (`var/engineering_state.json`); claimed or DONE items are silent. An instruction is actionable when it has no ack or its ack says AWAITING the engineering session (pickup-completed docs messages are not nagged). An item that stops being eligible is forgotten; a `--baseline` marks history closed.
- **Completion returns control:** `finish` computes the next eligible approved task (priority, deps met, Done history) and clears its notification record so the next 120 s cycle announces it at once (not after the interval), once; the command also prints "CONTROL RETURNS TO THE SESSION LOOP: run begin <id>" or why there is no eligible task. It spawns no worker.
- **Duplicate / claim rules:** `begin` on DONE = DUPLICATE_IGNORED; on STARTED held by a different LIVE session pid = ACTIVE_CLAIM (no duplicate run, no interruption); held by the same session or a dead pid = RESUME (recovery, one START).
- Limits unchanged: 120 s polling (reminders are bounded by that granularity, not sub-minute), session-open lifetime, 30-minute Monitor expiry with re-arm by the session. The exact Monitor ledger is in the next section.

## Protocol for Arya: ONE harmless bounded engineering proof (no manual paste)
Publish via the GitHub inbox, from the distinct sender, a message `ARYA-<yyyymmdd>-<hhmm>-engineering-proof` containing:
```
Type: ENGINEERING_PROOF
Nonce: <short unique token>
Ask: run `tools/engineering_session.py begin <message id>` and `finish <message id> --note "nonce <token>"`, then set the ack Stage to COMPLETED. No other work.
```
Pass criteria, each with its own evidence: (1) fetch + (2) delivery: pickup receipt/heartbeat for the id; (3) ACK on `research/agent-01-coordinator` with Stage "AWAITING the interactive engineering session"; (4) the Monitor notification "NEW INSTRUCTION <id>" in the session (the session reports the nonce back); (5) `docs/receipts/engineering/<id>.md` START naming pid + entrypoint `cli`/interactive, not pickup; (6) DONE with the result and the next eligible task; (7) ack Stage COMPLETED, and pickup state COMPLETED via reconcile. A docs-only pickup completion (no engineering receipt) does not count.

## Proven vs unproven
- **Proven (tests):** duplicate delivery does not run twice; restart/re-entry resumes one record; completion advances the next eligible task once honouring deps and Done history; pickup never completes an ENGINEERING_PROOF; reconciliation follows the ack.
- **Proven live in this session:** a real `begin` receipt for ARYA-2127 names pid 2937731 / `cli`; the Monitor is armed (task bdbh7vwvt).
- **UNPROVEN:** an end-to-end live proof without a paste (needs Arya's message above and the session to be open and armed); pickup watcher adoption of the new type (it re-execs on code change, not separately verified here); the watchdog still misreports this session (its code was not changed: it is an older long-running service, and a restart is outside this task).
- **If owner wants a stronger route:** exact permission change needed = approve `MBOS_ALLOW_TMUX_WAKE=1` for the watchdog AND run the coordinator inside tmux session `mbos-agent-01`; not requested here.

**Actual expiry/re-arm evidence:** Monitor brn9342yu (armed ~22:10Z, 120 s polling) delivered 2 events (instruction 2208, then the A-60 READY row) and expired after 30 minutes as documented; re-armed by the session at 2026-10-10T22:16:52Z as task b8bnoxds1. Nothing was delivered between expiry and re-arm by design (session-owned, 30-minute limit).

## Monitor ledger (receipt for ARYA-20261010-2203; times UTC; recorded 2026-10-10T23:00Z)
Evidence: the Monitor task output files' birth/modify times and the watcher process start time (`ps lstart`), converted from CDT (-0500). "Armed" for the older monitors is the time of its first output or the previous monitor's stop/expiry; only the current watcher's start is read from the process table.

| Monitor | Armed | Ended | How it ended | Why re-armed |
|---|---|---|---|---|
| bdbh7vwvt (one-shot code) | 21:31:04Z | about 21:45Z | MANUAL stop (TaskStop) | MANUAL code-upgrade re-arm for the A-65 reminder logic |
| be2ai9zvm (A-65 code) | about 21:45Z | 21:46:32Z | MANUAL stop | MANUAL fix re-arm: it announced 26 pre-cutoff history ids (flood), cutoff fix 6426a50 |
| brn9342yu | about 21:46:32Z | 22:16:32Z | NATURAL 30-minute expiry (3 events delivered) | natural-expiry re-arm |
| b8bnoxds1 | about 22:16:40Z | 22:46:37Z | NATURAL 30-minute expiry (3 events: A-60 reminders #2 to #4) | natural-expiry re-arm |
| **bi406dbuw (current)** | **22:46:41Z** (watcher pid 21015, `ps lstart`) | expires about **23:16:41Z** | pending | will be re-armed by this session when it expires |

- Re-arm mechanism: the session calls the Monitor tool again with `tools/next_work.py --watch 120` and `timeout_ms` 1800000 (the maximum); nothing re-arms it by itself, and nothing is delivered between an expiry and the re-arm.
- Last feed notifications on the current monitor: REMINDER #5 for READY row A-60 at 22:54:47Z, then NEW INSTRUCTION ARYA-20261010-2203-current-route-receipt at 22:56:49Z.
- Engineering claim for 2203: `begin` recorded STARTED at 22:56:54Z (interactive session pid 2937731, entrypoint cli), five seconds after the notification.
- Natural-expiry re-arms evidenced: two (brn9342yu to b8bnoxds1, b8bnoxds1 to bi406dbuw). Manual code-upgrade re-arms: two. A Monitor is still finite (30 minutes) and session-owned: this is progress only while the session is open and re-arms are actually performed; no liveness is claimed from a process or an old receipt.

