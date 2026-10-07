# Receipt: provenance correction, commit authorship (append-only; history NOT rewritten)

- **Date:** 2026-10-07
- **Actor:** Agent 01
- **Trigger:** Agent 07 finding P-07-2 / F-17

**FACT (verified with `git config --show-origin`):**
- `user.name` and `user.email` live in the SHARED `/home/michaelos/michael-business-os/.git/config`.
- `extensions.worktreeConfig` is unset.
- Each agent launch rewrites the shared identity, so commits get the identity of whichever agent launched last.

## Corrected authorship for `research/agent-01-coordinator`
All of these were authored by **Agent 01 (Coordinator)**, not by "Agent 07 Marketing" as git records:

| Commit | Subject |
|---|---|
| `acb6f3b` | round two start, status WORKING |
| `c6c5ad4` | durable spine |
| `7ed5705` | A1–A10 acceptance harness, CLI, RUNBOOK |
| `bed7609` | integration review, R1–R11 |
| `99e9ec0` | ADR-0010 + foreman loop |
| `bf215b2` | A-01 phase 1, R12, notify_decision, queue sync |

Evidence that these were Agent 01's work:
- each subject is prefixed `agent 01`
- each was pushed from worktree `/home/michaelos/business-os-worktrees/agent-01-coordinator` to `research/agent-01-coordinator`, which only Agent 01 writes.

Pushed history is NOT rewritten (git rules: no destructive rewrites). This receipt is the correction of record.

## Remedy
- **Interim (all agents, now; in `docs/COORDINATION.md`):** set the identity explicitly on every commit with `git -c user.name='Agent NN <Role>' -c user.email='michaelos+agent-NN-<role>@users.noreply.github.com' commit ...`. The shared value is not reliable.
- **Root cause (operator, outside the repo; not changed by Agent 01):** in `~/bin/mbos-agent`, run `git config extensions.worktreeConfig true` once. Then set the identity with `git config --worktree user.name/user.email` instead of the shared config.
- Agent 01's commits from this point on use explicit identity.
