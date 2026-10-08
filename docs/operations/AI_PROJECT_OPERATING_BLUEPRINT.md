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
