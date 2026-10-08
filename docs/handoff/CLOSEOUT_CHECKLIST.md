# Lane closeout checklist (ADR-0014; Aria ARIA-20261007-1945)

Purpose: after this, **no knowledge may depend on an old chat or tmux context.** A fresh bounded worker must be able to take the lane over cold from repo truth.

An agent closing out does these, in order, on its OWN branch:
1. `git fetch -q origin`; read `docs/status/READY_QUEUE.md` on `research/agent-01-coordinator`.
2. Finish the current task OR stop at a clean boundary. Do not leave a half-applied change.
3. Commit and push all valid code and tests (set your identity per commit: `docs/COORDINATION.md`).
4. Update `docs/status/AGENT_STATUS.md` accurately (`State: CLOSED`, last head, `Done:` lines).
5. Write receipts for completed consequential work (`docs/receipts/`).
6. Anything unfinished: add a row under `## Proposed tasks` in AGENT_STATUS with an acceptance condition. Agent 01 moves it to READY_QUEUE.
7. Write `docs/handoff/LANE_<NN>.md` (template below). Short: aim for under 150 lines. Facts, not narrative.
8. Verify `git status --porcelain` is empty or intentionally explained, and `git log origin/<branch>..HEAD` is empty (everything pushed).
9. Reply to Agent 01 with: branch head, the handoff path, and `git status` result. **Agent 01 verifies, then closes the session. Do not close it yourself.**

Do not delete worktrees or branches.

## `docs/handoff/LANE_<NN>.md` template
```
# Lane NN handoff
- Branch / head (pushed):
- Role and boundaries (what this lane owns; what it must never touch):
- Completed (task IDs, commits):
- Outstanding (task IDs, with acceptance, or "none"):
- Blockers (owner/external/dependency):
- Key files and entry points:
- Run commands (setup, tests, the one command that proves the lane is healthy), with expected result:
- Interfaces with other lanes (what you consume, what you provide, vendored copies and how to re-vendor):
- Known pitfalls (things that cost time or broke before):
- Open questions (UNKNOWN, with who can answer):
```
