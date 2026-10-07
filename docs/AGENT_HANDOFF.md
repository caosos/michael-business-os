# AGENT HANDOFF — Michael Business OS

## Why this exists
Future agents may replace current agents at any time. No agent should require Michael to reconstruct project history manually.

The repository is the authoritative memory.

## Project objective
Build a persistent AI business operating system that can work while Michael sleeps and help him operate independently without relying on traditional employment.

It must find opportunities, rank them, market services, track leads, support communications, record money/results, and continuously improve recommendations.

## Product philosophy
Optimize for profitable usefulness, not maximum extraction.

Solve a real problem
→ charge fairly
→ record result
→ learn economics
→ repeat what works

## Current business lanes
- mobile repair
- equipment repair
- furniture/equipment assembly
- drywall repair
- handyman/small repair
- smart-home installation
- accessibility-related mechanical work where appropriate
- value-add flips: trailers, mowers, generators, compressors, welders, tools, commercial/mechanical equipment, and similar assets

## Geographic/economic rule
Approximately 100 miles is a normal search radius, not a hard limit.

Distance is economic.

A farther opportunity can outrank a nearby one if expected value, profit, profit/hour, scarcity, or time-to-cash justify the travel.

## Decision interface
The eventual owner-facing interaction should be simple:

YES
NO
MODIFY
HOLD

The system does the information work; Michael performs owner decisions and physical work.

## Current agent lanes
### Agent 01 — Coordinator / Architect
Owns synthesis, architecture reconciliation, cross-agent conflicts, system contracts, status dashboard, and Round-Two plan.

### Agent 02 — Opportunity Discovery
Owns source research, collectors, source access strategy, normalization, dedup, polling, and discovery coverage.

### Agent 03 — Economics / Scoring
Owns formulas, risk/confidence, travel economics, expected value, profit/hour, ROI, time-to-cash, scarcity, and ranking logic.

### Agent 04 — CRM / State
Owns canonical durable state, entity model, receipts/provenance storage, audit/history, backup/recovery, and CRM projection strategy.

### Agent 05 — Governance / Security
Owns approvals, capabilities, policy enforcement, kill switches, spend limits, prompt-injection resistance, agent authority, and secrets boundaries.

### Agent 06 — Communications
Owns voice/SMS/email architecture, seller/customer workflows, call/SMS/email receipts, disclosure/consent constraints, and human handoff.

### Agent 07 — Marketing
Owns local SEO/AEO, GBP/Apple/Bing strategy, website/schema, reviews, attribution, contractor/referral outreach, content automation, and anti-spam rules.

## Work allocation: the foreman loop (Round Two onward; mandatory)
Read `docs/COORDINATION.md`. In short:
1. Read `docs/status/READY_QUEUE.md` and `docs/status/ACTIVE_WORK.md` from `origin/research/agent-01-coordinator`.
2. Claim the highest-priority READY task assigned to you, by pushing `Claimed: <ID>` in your `AGENT_STATUS.md`.
3. Finish it, push, and claim the next one.

Enter WAITING only when no compatible READY task exists. Every hash follows ADR-0010 (`docs/research/contracts/canonical/`).

## Durable reporting
Every agent:
- writes research to docs/research/
- writes status to docs/status/AGENT_STATUS.md
- writes proposed architecture decisions to docs/decisions/
- writes evidence/provenance receipts to docs/receipts/
- commits and pushes meaningful progress

Agent 01 also maintains docs/status/ALL_AGENTS.md.

## Fact discipline
Use these labels:

FACT
Verified from code, docs, repo state, authoritative sources, or direct testing.

INFERENCE
Reasonable conclusion not directly verified.

RECOMMENDATION
What the agent thinks should be done.

UNKNOWN
Not yet verified.

Never present an inference as fact.

## Owner interruption rule
Before asking Michael:
1. research it
2. inspect project docs
3. inspect relevant branches
4. decide if it is genuinely an owner decision

If yes:
- record it in status first
- push status
- then ask

Michael should not be asked routine technical questions.

## Git rules
- no merge to main without explicit authorization
- no editing another agent's worktree
- no editing another agent's branch
- no destructive rewrites
- no production deployment during research/design
- no silent cross-system changes

## Worktree layout
/home/michaelos/business-os-worktrees/agent-01-coordinator
/home/michaelos/business-os-worktrees/agent-02-opportunity
/home/michaelos/business-os-worktrees/agent-03-economics
/home/michaelos/business-os-worktrees/agent-04-state
/home/michaelos/business-os-worktrees/agent-05-governance
/home/michaelos/business-os-worktrees/agent-06-communications
/home/michaelos/business-os-worktrees/agent-07-marketing

## Launch commands
As michaelos:

~/bin/mbos-agent 1
~/bin/mbos-agent 2
~/bin/mbos-agent 3
~/bin/mbos-agent 4
~/bin/mbos-agent 5
~/bin/mbos-agent 6
~/bin/mbos-agent 7

From another sudo-capable account:

sudo -iu michaelos /home/michaelos/bin/mbos-agent N

## SSH setup concept
Business OS should be reachable independently through a local SSH alias:

ssh michaelos

That alias should target the same EliteDesk host as the CAOSCare SSH alias but use:
User michaelos

The server-side authorized_keys for michaelos must contain the local machine's SSH public key used to reach the EliteDesk.

## GitHub SSH setup concept
The michaelos account has a dedicated GitHub SSH key and config alias:

Host github-michaelos
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_michaelos
    IdentitiesOnly yes

Git remote should therefore be:

git@github-michaelos:caosos/michael-business-os.git

## Claude Code setup
Use the native user-owned Claude install when available:

/home/michaelos/.local/bin/claude

PATH should prefer:

$HOME/.local/bin

over /usr/bin.

## Provenance rule
A recommendation must be reconstructable.

For consequential recommendations preserve:
- source
- URL/repo/document
- timestamp
- agent
- what was checked
- observation
- confidence
- uncertainty
- related output

## Approval boundary
Until explicitly delegated, agents may autonomously research and draft but not create external commitments.

External world-changing actions require owner approval.

## Non-negotiable separation
This project is NOT CAOSCare.

Do not:
- reuse CAOSCare branches
- write into CAOSCare repos
- deploy to CAOSCare
- change CAOSCare services
- use CAOSCare as a test environment

## Handoff checklist for replacement agents
Before continuing work:

- read START_HERE.md
- read this file
- fetch origin
- confirm current branch/worktree
- read own AGENT_STATUS.md
- read coordinator ALL_AGENTS.md
- inspect relevant ADRs
- inspect latest research reports
- verify no uncommitted work exists
- read docs/COORDINATION.md, READY_QUEUE.md and ACTIVE_WORK.md
- claim a READY task in your own status (State: WORKING, Claimed: <ID>)
- commit and push that status
- do the task; on completion push, then claim the next READY task

## End-of-session checklist
Before ending:

- update AGENT_STATUS.md
- record blockers/unknowns
- list files produced
- record next action
- commit
- push
- do not leave important truth only in terminal history

## Guiding rule
Capture everything.
Execute one thing.
Finish it.
Then move.
