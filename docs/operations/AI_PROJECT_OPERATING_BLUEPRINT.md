# AI PROJECT OPERATING BLUEPRINT

Status: Michael's standing operating model for AI-assisted projects
Scope: Applies to Michael Business OS / Deal Sniffer and should be reused as the default operating pattern for future projects unless a project-specific rule overrides it.

## 1. Core principle

Persistent truth belongs in durable project state, not in a long chat.

Conversations, agent sessions, and model contexts are temporary workers.
The durable system is:
- repository
- database
- task queue
- decisions / ADRs
- receipts / provenance
- handoffs
- tests
- runbooks
- telemetry

If important knowledge exists only inside an agent conversation, the system is not operating correctly.

## 2. Control-plane model

Use a small persistent control plane and short-lived execution workers.

### Persistent by default
- one coordinator / foreman session or service
- durable task queue
- durable project state
- dashboard / observability
- runtime/watchdog service when needed

### Temporarily persistent when justified
A QA, integration, or incident-response session may remain open while a tightly scoped wave is active.

It must close when that wave is complete.

### Ephemeral by default
Specialist coding/research workers should:
1. start fresh;
2. load only required durable context;
3. claim one bounded task;
4. execute;
5. test;
6. commit/push;
7. write receipts/status/handoff as needed;
8. exit.

Do not keep a specialist alive merely because its lane exists.

## 3. Can the system open workers automatically?

Yes. The target architecture is for the coordinator/runtime to launch bounded worker sessions itself.

Preferred pattern:
- coordinator chooses task + lane + model;
- launcher opens a fresh Claude Code / agent session;
- worker receives task-scoped context;
- worker completes or stops at a defined blocker;
- worker records telemetry and exits.

A human should not need to manually open seven terminals for normal operation.

Until automatic launching is fully implemented, manual starts are acceptable, but the blueprint remains the same.

## 4. Task contract

Every task must have:
- unique ID
- project
- lane / capability
- priority
- dependencies
- exact objective
- acceptance criteria
- authority boundary
- required outputs
- expected tests
- owner / worker
- status

Valid states should be explicit, e.g.:
- READY
- CLAIMED
- WORKING
- BLOCKED
- NEEDS_OWNER
- DONE
- CLOSED

No agent should invent untracked cross-project work.

## 5. Coordinator responsibilities

The coordinator is responsible for the system, not just its own coding lane.

It must:
- keep the queue accurate;
- dispatch useful work;
- prevent duplicate/conflicting work;
- unblock dependencies;
- turn verified gaps into bounded tasks;
- keep workers supplied with useful work;
- stop make-work;
- consolidate owner questions;
- enforce project boundaries;
- monitor usage/efficiency;
- choose the proper model/worker strategy;
- ensure every closed lane has a durable handoff;
- preserve repo truth before terminating sessions.

The coordinator should not become the only implementer.

## 6. Owner-interrupt rule

Michael should be interrupted only when a genuine owner decision is required.

A valid owner interruption includes:
- business-policy choice
- spend / purchase / external commitment
- credential/account action
- legal-risk posture
- irreversible product direction
- unavailable external resource
- explicit human judgment the system cannot legitimately make

Before asking Michael, the coordinator should provide:
- exact question
- why it matters
- recommended default
- available options
- what is blocked
- what can continue without him

Technical reversible decisions should normally be resolved by the coordinator/agents.

## 7. Model routing

Do not use the strongest model for everything.

Default routing philosophy:

### Routine bounded implementation
Use a strong efficient coding model such as Sonnet-class.

Good for:
- implementation
- tests
- adapters
- docs
- ordinary refactors
- bounded research

### Difficult planning / integration
Use Opus-class or equivalent.

Good for:
- architecture
- multi-lane integration
- difficult debugging
- high-risk refactors
- complex synthesis

### Hardest long-horizon work
Use Fable-class or strongest available model only when justified.

Good for:
- large asynchronous architecture work
- major migrations
- difficult multi-system reasoning
- deep research
- problems that repeatedly defeat cheaper models

### Lighter models
Use cheaper/faster models for repetitive low-risk classification, extraction, formatting, or simple transformations when available.

Every model-selection decision should be observable.

## 8. Escalation policy

Start with the cheapest capable model.

Escalate when:
- repeated failure
- low confidence
- architecture conflict
- large cross-file/cross-system change
- difficult root cause
- high-risk decision

Record:
- initial model
- reason for escalation
- retry count
- final model
- outcome

Do not escalate just because a stronger model exists.

## 9. Context discipline

Long context is expensive and can reduce throughput.

Default behavior:
- fresh worker for a new bounded task
- targeted context only
- durable state loaded from repo/DB
- avoid dragging unrelated chat history forward

Continue an existing session only when its private context is materially valuable.

When a session must continue:
- compact it when appropriate
- clear unrelated context
- checkpoint important state externally first

Avoid giant persistent >150k-context workers unless the task demonstrably benefits.

## 10. Parallelism discipline

Parallelism should improve throughput, not merely increase agent count.

Run work in parallel when tasks are:
- independent
- clearly bounded
- non-conflicting
- useful on the critical path

Avoid:
- seven heavyweight sessions doing loosely defined work
- duplicate analysis
- agents competing for the same files
- parallel work whose merge/integration cost exceeds the benefit

Measure output per usage window, not number of active agents.

## 11. Durable handoff standard

Before closing any persistent worker/lane, write a handoff containing:
- role/lane
- branch/head
- completed tasks
- current task state
- unfinished tasks
- blockers
- important files
- relevant ADRs
- tests/run commands
- known pitfalls
- external dependencies
- owner decisions still needed

No agent should be closed if important information exists only in its chat.

## 12. Session closeout

Before terminating a long-lived session:
1. fetch/sync current project truth;
2. finish at a clean boundary;
3. commit/push valid work;
4. update status;
5. write receipts;
6. queue unfinished work;
7. write handoff;
8. verify git state;
9. terminate session.

Do not delete worktrees/branches during routine closeout.

## 13. Receipts and provenance

Standing law:

> No action without a receipt. No receipt without provenance.

Consequential actions should record:
- actor/worker
- task
- timestamp
- reason
- inputs
- source/provenance
- model/tool when relevant
- result
- commit/artifact
- next action

Human decisions should also be durable when they change project behavior.

## 14. Human approval boundaries

Autonomous work may include:
- research
- discovery
- analysis
- calculations
- drafting
- testing
- code changes inside authorized repo/worktree
- documentation
- internal recommendations

Protected actions generally require explicit authority:
- spend
- purchase
- external message/send
- publish
- bid/offer
- booking/scheduling with external parties
- account changes
- deployment
- price changes
- irreversible external commitments

Project-specific policy may tighten these boundaries.

## 15. Observability

Every project should expose an operations dashboard.

Minimum worker telemetry:
- active workers
- queued tasks
- blocked tasks
- persistent sessions
- task throughput
- task duration
- model mix
- retries
- escalations
- failures
- stale workers
- commits/results
- test status

Where supported, capture:
- session ID
- model
- start/end time
- duration
- API/model time
- turns
- context/usage metadata
- computed cost estimate
- success/error

Never present an estimated model cost as a confirmed bill unless it actually is one.

## 16. Usage/quota monitoring

When a provider exposes usage windows/quotas, monitor them.

For Claude/Anthropic specifically, track supported values when available:
- current session/window utilization
- weekly utilization
- model-specific usage pools
- reset times
- context-size contributors
- parallel-session contributors

Use only supported interfaces.
Do not scrape undocumented private endpoints or bypass provider controls.

If a quota metric cannot be retrieved programmatically:
- mark it UNKNOWN/manual;
- allow manual snapshot entry;
- do not fabricate it.

## 17. Project isolation

Each project should have:
- explicit repository
- explicit branch/worktree policy
- explicit runtime account/user when useful
- clear "do not touch" boundaries
- project-specific START_HERE
- project-specific decisions
- project-specific queue
- project-specific handoff

Cross-project reuse should happen through documented shared blueprints/libraries, not accidental context bleed.

## 18. Onboarding order for a fresh worker

A fresh worker should read only what it needs, in this order:

1. project START_HERE
2. this operating blueprint
3. project-specific product blueprint
4. assigned task
5. lane handoff/status
6. relevant ADRs/contracts
7. targeted source files/tests

Do not load the entire history unless the task requires it.

## 19. Watchdog / dispatcher

The runtime may use a watchdog/dispatcher to:
- detect idle persistent coordinator/QA sessions;
- launch bounded workers;
- restart failed worker processes;
- detect stale claims;
- alert on blocked queues;
- keep the coordinator loop alive.

The watchdog should not blindly type into every idle shell forever.

Its job is to maintain the control plane and launch useful bounded work.

## 20. Professional operating target

The intended operating shape is:

Michael
  ↓
Aria / Operator UI
  ↓
Persistent coordinator / orchestration service
  ↓
Durable queue + workflow engine
  ↓
Fresh bounded workers
  ↓
Models + tools + APIs + DB + repo
  ↓
Tests + receipts + telemetry + outcomes
  ↓
Learning / updated project truth

Persistent:
- database
- repository
- task queue
- coordinator runtime
- dashboard

Disposable:
- individual agent conversations

## 21. Standing optimization rule

For every project, periodically ask:

- Are we storing too much knowledge in context instead of durable state?
- Are we using too many persistent agents?
- Are we using the strongest model where a cheaper one would work?
- Are workers getting enough context but not too much?
- Is parallelism actually improving throughput?
- Are model/usage metrics visible?
- Can a fresh worker take over without asking Michael to repeat himself?
- Can the system recover cleanly after restart?
- Are owner interruptions minimized?
- Are receipts/provenance complete?

If the answer to any of these is no, create bounded corrective work.

## 22. Reuse rule

This blueprint is intended to be copied or referenced by future Michael projects.

Project-specific rules may override it, but any override should be explicit and durable.

The operating philosophy stays:

> Durable truth over chat memory.
> One control plane, many disposable workers.
> Use the cheapest capable model.
> Measure everything.
> Interrupt Michael only when necessary.
> Preserve provenance.

## 23. Continuous-progress rule

Michael's standing preference is continuous useful progress.

- **Never idle merely because the last task ended.** When useful approved work remains, immediately start the next highest-value bounded task.
- **Build first, then refine.** Prefer a working, testable implementation over extended speculative design when the next safe implementation step is known.
- **Use the most economical capable model.** Default to the cheapest model that can do the task reliably; escalate only when complexity, failure, risk, or cross-system reasoning justifies it.
- **Optimize for output, not agent count.** Keep only enough concurrent bounded workers to improve throughput without wasting quota or creating merge/conflict overhead.
- **When the queue runs dry, derive the next bounded task from the current acceptance gap, release gap, verified defect, missing integration, test failure, or operator-usability gap.** Do not create cosmetic busywork.
- **Stop only for a real blocker:** explicit owner decision, unavailable external credential/resource, safety/governance boundary, provider quota, or a hard dependency that no other useful work can bypass.
- **If a blocker affects one task, continue other compatible work in parallel.** Michael should not be required to restart momentum manually.
- **Progress must be measurable:** each worker leaves tests, commit/artifact, receipt/provenance, telemetry, and the next-state update.

Operating goal:

> Maximum useful progress per dollar/token/hour, with continuous motion and reversible iteration.

---
## Michael Business OS: project-specific overrides (added by Agent 01; the blueprint text above is Aria's, verbatim)
Source: ARIA-20261007-2000, adopted 2026-10-09. Where this section differs, it wins for this project only.
- **Persistent control plane:** Agent 01 only (`mbos-agent-01`). QA is a fresh worker per window, not persistent (ADR-0014).
- **Launching:** `tools/worker.py` (one task, supported `claude -p`, telemetry, quota guard); `tools/dispatcher.py` launches workers automatically (daemon, tmux session `mbos-dispatcher`); `tools/foreman.py` reports idle/stale state. Specialist-lane tasks are auto-dispatched; lane-01 tasks run in a side worktree and are merged by Agent 01 after review.
- **Hard boundaries that no operating rule overrides:** DRY-RUN only; no seller/customer contact, spend, publishing or deployment without Michael; $500 protected principal; the workflow login never holds `approver` or `owner_channel` (R14, ADR-0014); every action has a receipt with provenance.
- **Limits:** at most 2 heavy workers in parallel, at most 3 attempts per task, at most 12 launches per hour, quota guard at 90% of the 5-hour or weekly window (`config/model_router.v1.json`).
- **Onboarding order for a fresh worker here:** `START_HERE.md`, this blueprint, `docs/product/DEAL_SNIFFER_START_HERE.md`, `docs/COORDINATION.md`, the lane handoff, the assigned task row, relevant ADRs/contracts, targeted files.
- **Where the blueprint is not yet true here:** Fable has not been used (no long-horizon task has justified it); per-model weekly quota (Fable %) and the contributor splits have no supported programmatic source; the host scheduler (cron/systemd) that would restart the dispatcher after a reboot is not installed (OWNER_ACTIONS D2). Until then Agent 01 starts the dispatcher in tmux.
- **Stage separation and troubleshooting record (ARYA-0447):** pickup/ACK, execution, code completion, staging acceptance and live acceptance are five different facts and each needs its own evidence; a pickup `COMPLETED` is coordination only. Message ids are immutable; an amendment needs a new id and a verified handoff to the owning task. The symptom/cause/fix/rollback history lives in the "Troubleshooting history" subsection at the end of this file (RUNBOOK.md section 7 should link here; RUNBOOK is outside the docs-only executor scope); do not start a second log.

### Troubleshooting history: coordination and delivery (ARYA-0447; links, not copies)
Stage vocabulary (never merge these): **pickup/ACK** (inbox_pickup saw and queued the id) -> **execution** (a bounded executor or worker actually ran) -> **code complete** (commit + tests on a lane branch) -> **staging acceptance** (real-browser evidence on staging) -> **live acceptance** (owner-gated reload; none yet). A message id is immutable; an amendment ships as a NEW id plus a verified handoff to the owning task, never a rewritten already-ACKed payload.

| Symptom (observed) | Cause: confirmed / suspected | Fix and evidence | Rollback / limit | Next owner |
|---|---|---|---|---|
| Same id executed twice (ARYA-0328) | CONFIRMED: pickup ran a message another actor had already ACKed | `7bd5160` (`tools/inbox_pickup.py`, regression test; id already acknowledged is never run twice) | revert commit; limit: relies on `var/pickup/state.json` + ACK file | done |
| Pickup status read idle/stale while busy (04:30:16Z, `currently_running: null` during 0431) | CONFIRMED from code: `HEARTBEAT_S=600` vs `ttl_sec=300`; field cleared before publish; sync deliver blocks heartbeat. Details: `docs/receipts/pickup/ARYA-20261010-0431-execution-handoff-proof.md` | NOT FIXED. Queue row **A-52** (code, lane 01). Tests: none yet. Treat null/stale pickup status as UNKNOWN | n/a | Agent 01 code session |
| "COMPLETED" read as work done | CONFIRMED: pickup COMPLETED = a docs-only coordination executor finished; not engineering | Pickup receipts under `docs/receipts/pickup/`; engineering proof is the lane commit/receipt | n/a | all readers |
| Strict price/radius lets unknown through (`market_search.py` at `5b42655`/`b1a3d16`; tests encode it) | CONFIRMED by reading code per 0433; not yet fixed | **F-51 (A)** amended scope: `docs/handoff/F-51-amendment.md`; F-52 closes whatever F-51 misses | live /market unchanged until the owner-gated reload | lane 06 (F-51, then F-52) |
| Amendment may not reach a running worker | CONFIRMED: F-51 launched 04:28:50Z, before the amendment; a `claude -p` worker cannot be messaged | Pickup ACK `docs/messages/acks/ARYA-20261010-0433-f51-scope-handoff.md` stays BLOCKED until a lane-06 receipt/status cites "AMENDMENT" | do not restart or duplicate the worker | lane 06 / Agent 01 |
| Pickup stops on reboot/logout | CONFIRMED: tmux session `mbos-pickup`, `Linger=no` | Unit prepared, **NOT INSTALLED**: `docs/operations/PICKUP_PERSISTENCE.md`, `ops/systemd/mbos-pickup.service`. Stays "prepared" until an installation receipt shows `systemctl --user status` and `Linger=yes` | rollback steps in that file | owner (linger step) |

Roles, so nobody invents a second one: **pickup** = `tools/inbox_pickup.py` (docs-only side executor, tmux `mbos-pickup`); **dispatcher** = `tools/dispatcher.py` (launches lane workers for READY rows, tmux `mbos-dispatcher`); **interactive wake** = the interactive Agent 01 session (queue/code owner; pickup does not need it).
