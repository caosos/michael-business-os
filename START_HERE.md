# START HERE — Michael Business OS

## Purpose
Michael Business OS is a standalone, self-hosted AI business operating system for Michael. It is separate from CAOSCare and all other projects.

The system exists to:
- discover money-making opportunities continuously
- normalize and deduplicate them
- research comps and relevant facts
- score them by economics, risk, time, confidence, and fit
- recommend the best next actions
- present decisions as YES / NO / MODIFY / HOLD
- act only within explicit authority
- record receipts and provenance
- track outcomes
- learn from results
- support marketing, CRM, communications, and future phone/SMS/email automation

## Core operating law
NO ACTION WITHOUT A RECEIPT.
NO RECEIPT WITHOUT PROVENANCE.

## Primary lifecycle
DISCOVER
→ NORMALIZE
→ RESEARCH
→ SCORE
→ RECOMMEND
→ MICHAEL APPROVES
→ ACT
→ RECEIPT
→ OUTCOME
→ LEARN
→ REPEAT

## Project isolation
Business OS work belongs only here:

Repository:
caosos/michael-business-os

EliteDesk owner:
michaelos

Primary checkout:
/home/michaelos/michael-business-os

Agent worktrees:
/home/michaelos/business-os-worktrees/

Prompts:
/home/michaelos/business-os-prompts/

Launcher:
/home/michaelos/bin/mbos-agent

DO NOT TOUCH:
- CAOSCare repositories
- CAOSCare branches
- CAOSCare production
- another agent's branch
- another agent's worktree

## SSH separation
Desired local aliases:

ssh caoscare
- logs into the CAOSCare account/workspace

ssh michaelos
- logs into the Business OS account/workspace

The remote Business OS Linux user is:
michaelos

Expected Business OS shell prompt:
michaelos@caoscare1-hp-elitedesk:~$

## GitHub SSH identity
Business OS uses its own GitHub SSH identity under:
/home/michaelos/.ssh/

GitHub host alias:
github-michaelos

Repository remote:
git@github-michaelos:caosos/michael-business-os.git

## Claude Code
Business OS should use the user-owned native Claude Code install for michaelos.

Preferred binary:
/home/michaelos/.local/bin/claude

Do not rely on /usr/bin/claude if the native install exists.

## Agent launcher
Agents are launched with:

/home/michaelos/bin/mbos-agent N

where N is:

1 — Coordinator / Architect
2 — Opportunity Discovery
3 — Economics / Scoring
4 — CRM / State
5 — Governance / Security
6 — Communications
7 — Marketing

From a different login account, switch first:

sudo -iu michaelos /home/michaelos/bin/mbos-agent N

## Agent branches
research/agent-01-coordinator
research/agent-02-opportunity
research/agent-03-economics
research/agent-04-state
research/agent-05-governance
research/agent-06-communications
research/agent-07-marketing

Each worktree has a pinned local Git identity. The launcher reasserts that identity at startup.

## Work allocation: the foreman loop (Round Two onward; mandatory)
Read `docs/COORDINATION.md`. In short:
1. Read `docs/status/READY_QUEUE.md` and `docs/status/ACTIVE_WORK.md` from `origin/research/agent-01-coordinator`.
2. Claim the highest-priority READY task assigned to you, by pushing `Claimed: <ID>` in your `AGENT_STATUS.md`.
3. Finish it, push, and claim the next one.

Enter WAITING only when no compatible READY task exists. Every hash follows ADR-0010 (`docs/research/contracts/canonical/`).

## Reporting protocol
Every agent must maintain:

docs/status/AGENT_STATUS.md

Agent 01 additionally maintains:

docs/status/ALL_AGENTS.md

Round-One reports live under:

docs/research/

Architecture decisions live under:

docs/decisions/

Research/action receipts live under:

docs/receipts/

If important work exists only in a terminal, it is not durable project state.

## Required status values
WORKING
BLOCKED
WAITING
COMPLETE

## Required reporting behavior
Update and push status:
- at work start
- after major milestones
- when blocked
- before asking Michael a question
- after important decisions
- before ending a session
- on completion

Never invent another agent's progress. Read its branch.

## What only Michael can do
See `docs/status/OWNER_ACTIONS.md` (decisions, credentials, his own model knowledge, host tasks).

## Michael's role
Michael should not be the messenger between agents.

Michael should increasingly make only high-value owner decisions:
- YES
- NO
- MODIFY
- HOLD

Technical questions should be researched and resolved by agents/coordinator unless they are true owner decisions.

## Aria's role
Aria is the liaison between Michael and the agent swarm.

When Michael says:
"Check the agents."

Aria should inspect GitHub and report:
- who is working
- who is done
- who is blocked
- what they found
- where recommendations conflict
- which owner decisions remain
- whether architecture is converging
- the next best move

## Coordinator role
Agent 01 is the technical coordinator.

It reconciles specialist recommendations and must not lock the architecture before cross-agent review.

The coordinator owns synthesis, conflict resolution, integration planning, and Round-Two assignments.

## Round-One rule
Round One is research/design only.

No:
- deployment
- purchases
- seller/customer contact
- publishing
- SMS/email/calls
- production modification
- CAOSCare work
- merge to main

## Safety boundary
Autonomous initially:
- discovery
- research
- collection
- comps
- calculations
- ranking
- drafting

Approval required initially:
- sending messages
- making offers
- spending money
- purchases
- publishing
- scheduling
- price changes
- phone calls
- SMS
- email
- external commitments

## Architecture principle
Prefer OSS/self-hosted for the core.
Use paid services where they clearly win on reliability, speed, or ROI.

Our data and business logic remain ours.
External providers should be replaceable.

## Before doing anything
A new agent must read:
1. START_HERE.md
2. docs/AGENT_HANDOFF.md
3. docs/status/ALL_AGENTS.md if present
4. its own branch docs/status/AGENT_STATUS.md
5. relevant docs/research/ and docs/decisions/

Then continue from durable state, not from assumptions.
