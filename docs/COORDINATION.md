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
- **Only mark a task CLAIMED after the agent's own claim is pushed** (06 caught me pre-marking F-07). Use "assigned" in ACTIVE_WORK until then.
- **Never leave an agent idle while compatible READY work exists.** If a lane runs dry, create tasks from integration gaps.
- **Never become passively WAITING myself.** When my next task is blocked, I take another READY task (`A-0x`).
- **Technical decisions are mine.** Only business-policy questions go to Michael (`docs/status/MICHAEL_DECISIONS.md`).
- **Critical-path work is P0,** and its dependents are marked BLOCKED with the blocking task ID.

```bash
for b in 02-opportunity 03-economics 04-state 05-governance 06-communications 07-marketing; do
  echo "== $b $(git log -1 --format='%h %cr' origin/research/agent-$b)"
  git show origin/research/agent-$b:docs/status/AGENT_STATUS.md | grep -E '^(State|Claimed|Done|Blocked)' ; done
```

## Continuous execution / owner-interrupt rule (Michael directive)

The goal is not to keep agents cosmetically busy. The goal is to keep useful project work advancing until the current scope is complete or Michael is genuinely required.

- **Agent 01 must continuously dispatch useful work.** If an agent finishes a task, Agent 01 immediately assigns the next highest-value compatible READY task.
- **An empty lane is not a reason to idle while useful work remains.** Agent 01 must derive bounded, testable tasks from open acceptance gaps, release findings, integration gaps, QA failures, documentation/runbook gaps, source-adapter work, or blocked dependents, then add them to READY_QUEUE before assignment.
- **Do not create make-work.** Every generated task must have a concrete acceptance condition and advance release readiness, live-readiness, operator usability, reliability, evidence quality, or a documented future dependency.
- **Agents continue automatically after every completion.** Finish → push receipt/status → claim next assigned/compatible task → work. Michael is not the dispatcher.
- **WAITING is allowed only when no useful compatible work can proceed without one of these:**
  1. a specific Michael business/policy decision,
  2. an unavailable external credential/account/provider,
  3. a hard dependency owned by another active task,
  4. a safety/governance boundary that forbids proceeding.
- **If Michael is required, stop at the smallest decision boundary.** Write one consolidated owner question with: exact decision, why it matters, recommended default, options, what is blocked, and what can continue in parallel. Push it to repo truth and notify Agent 01.
- **Do not stop merely because the originally assigned prompt is complete.** The work loop ends only when the current project scope/release objective is complete, or all remaining work is legitimately blocked under the rule above.
- **Agent 01 must keep READY_QUEUE deep enough for parallel execution.** When fewer agents have actionable work than available lanes, replenish the queue from verified gaps before allowing idle time.

## Commit identity (provenance; P-07-2)
The shared `.git/config` identity is overwritten by whichever agent launched last, so **always set your identity per commit**:
`git -c user.name='Agent NN <Role>' -c user.email='michaelos+agent-NN-<role>@users.noreply.github.com' commit …`
Check it with `git log -1 --format='%an'` before pushing. The correction of record for past mislabelled commits is in `docs/receipts/2026-10-07-provenance-correction-commit-authorship.md`.

## Non-negotiables (unchanged)
- DRY-RUN only: no sends, spend, publishing, contact or deployment.
- No action without a receipt. No receipt without provenance.
- Never merge to main. Never edit another agent's branch or worktree.
- Every hash follows ADR-0010 (MBOS-CJSON-1 / MBOS-RH-1). Verify with `docs/research/contracts/canonical/vectors.json`.
