# COORDINATION: the foreman loop (all agents, permanent)

Michael Business OS agents coordinate through GitHub. Michael is not the messenger. This loop applies to every agent, including newly started or restarted ones.

## Authoritative files (on `research/agent-01-coordinator`)
| File | Purpose |
|---|---|
| `docs/status/READY_QUEUE.md` | Every task: ID, lane, dependencies, status (READY/CLAIMED/BLOCKED/DONE), assigned agent, acceptance |
| `docs/status/ACTIVE_WORK.md` | What each agent is doing now, since when, and what is next |
| `docs/integration/ROUND_TWO_INTEGRATION.md` | Binding technical rulings (R1–R11) |
| `docs/decisions/INDEX.md` | ADR registry, including ADR-0010, the canonical hashing rule |
| `docs/research/contracts/` | Frozen contracts + `canonical/` (normative hashing) |

You cannot edit another agent's branch, so read the queue with:

```bash
git fetch -q origin && git show origin/research/agent-01-coordinator:docs/status/READY_QUEUE.md
```

## The loop (every agent)
1. **Start or resume.** Read START_HERE.md, your own `AGENT_STATUS.md`, `READY_QUEUE.md` and `ACTIVE_WORK.md`.
2. **Claim.** Pick the highest-priority task with status **READY** whose *Agent* column is you. If none exists, pick one marked for your lane or "ANY". Write `Claimed: <TASK-ID>` and `State: WORKING` in your `AGENT_STATUS.md`, then commit and push **before** starting.
   - The earliest pushed claim wins. If you find that another agent pushed a claim on the same task earlier, drop yours and pick another.
   - Never work on a task that is CLAIMED by someone else, or on one assigned to another agent.
3. **Work.** Do the work on your own branch only. Keep it DRY-RUN only. Every consequential step gets a receipt with provenance.
4. **Finish.** When the acceptance condition is met:
   - push code, tests and a `docs/receipts/` entry
   - set `Done: <TASK-ID> @ <commit>` in your `AGENT_STATUS.md`
   - push again
5. **Continue automatically.** Go back to step 2. **Only set `State: WAITING` when the queue has no READY task you can do**, and then name the task IDs you are waiting on.
6. **Blocked?** Set `Blocked: <TASK-ID> on <dependency>` in your `AGENT_STATUS.md`, push, and take another READY task. Never sit idle on a blocker.
7. **Found new work?** Add it under `## Proposed tasks` in your `AGENT_STATUS.md`. Agent 01 triages it into the queue. Do not start unqueued work that crosses lanes.

## The coordinator (Agent 01) loop
- **Sync after every push I make, and whenever a peer pushes.**
  1. Run `git fetch`.
  2. Read every `AGENT_STATUS.md` (one-liner below).
  3. Reflect claims and DONEs into `READY_QUEUE.md` and `ACTIVE_WORK.md`.
  4. Unblock dependents.
  5. Push.
- **Never leave an agent idle while compatible READY work exists.** If a lane runs dry, create tasks from integration gaps.
- **Never become passively WAITING myself.** When my next task is blocked, I take another READY task (`A-0x`).
- **Technical decisions are mine.** Only business-policy questions go to Michael (`docs/status/MICHAEL_DECISIONS.md`).
- **Critical-path work is P0,** and its dependents are marked BLOCKED with the blocking task ID.

```bash
for b in 02-opportunity 03-economics 04-state 05-governance 06-communications 07-marketing; do
  echo "== $b $(git log -1 --format='%h %cr' origin/research/agent-$b)"
  git show origin/research/agent-$b:docs/status/AGENT_STATUS.md | grep -E '^(State|Claimed|Done|Blocked)' ; done
```

## Commit identity (provenance; P-07-2)
The shared `.git/config` identity is overwritten by whichever agent launched last, so **always set your identity per commit**:
`git -c user.name='Agent NN <Role>' -c user.email='michaelos+agent-NN-<role>@users.noreply.github.com' commit …`
Check it with `git log -1 --format='%an'` before pushing. The correction of record for past mislabelled commits is in `docs/receipts/2026-10-07-provenance-correction-commit-authorship.md`.

## Non-negotiables (unchanged)
- DRY-RUN only: no sends, spend, publishing, contact or deployment.
- No action without a receipt. No receipt without provenance.
- Never merge to main. Never edit another agent's branch or worktree.
- Every hash follows ADR-0010 (MBOS-CJSON-1 / MBOS-RH-1). Verify with `docs/research/contracts/canonical/vectors.json`.
