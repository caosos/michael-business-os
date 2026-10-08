# ARIA-20261007-2145-keep-workers-running-until-blocked-or-done

- **ID:** ARIA-20261007-2145-keep-workers-running-until-blocked-or-done
- **Created:** 2026-10-07
- **Sender:** Aria, acting as Michael's liaison
- **Type:** OWNER_INPUT + IMMEDIATE_TASK_REQUEST
- **Priority:** P0 operational behavior
- **Authority:** internal repo/build/test work only; preserve all DRY-RUN and governance boundaries.

## Michael's directive

Michael should not have to keep asking for workers to be launched.

From now on, while useful READY work exists and quota/governance permits it:

> **Keep bounded workers working until the useful queue is complete or a genuine owner/external/governance blocker is reached. Choose the right model automatically. Do not wait for Michael to ask again.**

This is the intended behavior of ADR-0014 and the AI Project Operating Blueprint.

## Immediate action

1. Fetch and reconcile current queue/status.
2. Read supported quota telemetry.
3. If quota guard permits, launch bounded workers NOW for the highest-value compatible READY work.
4. Keep concurrency efficient rather than maximal:
   - default 1-2 simultaneous heavy workers;
   - parallelize only independent work;
   - avoid recreating the old 7-long-lived-session pattern.
5. Continue dispatching automatically after each completion.
6. If no specialist READY work remains, Agent 01 continues its own highest-value READY task.
7. Do not pause merely because a worker exits.

## Model routing

Use the accepted router, not manual owner selection:

- Sonnet: default implementation/tests/docs/bounded fixes.
- Opus: difficult integration, QA synthesis, complex debugging, cross-lane reasoning.
- Fable: only genuinely hard long-horizon work where it is justified and quota permits it.
- Escalate only on the router's defined failure/complexity criteria.

Record routing/model/turns/duration/retry/escalation telemetry.

## Current queue facts to reconcile

At the last liaison check:
- A-31 bounded-worker acceptance is DONE.
- C-23 was completed by a fresh Sonnet worker.
- G-12 was completed by a fresh Opus QA worker.
- A-32/A-33/A-34 are DONE.
- A-35 remains READY and is concrete useful work (21 residual strict-xfail cases).
- Other older READY rows may be stale and must be reconciled rather than blindly launched.

## Coordinator behavior required

Agent 01 must not sit at an idle prompt while:
- useful READY work exists;
- quota guard allows work;
- no owner/external/governance blocker prevents it.

If Agent 01 itself cannot be used as an ephemeral lane-01 worker because its persistent session owns that lane, it should either:
- execute the lane-01 task itself immediately; or
- safely reassign a bounded implementation/QA task to an appropriate specialist lane with explicit queue provenance and acceptance criteria.

Do not ask Michael to manually launch ordinary workers.

## Scheduler gap

The host scheduler/service is still the final automation gap. Until it is installed, Agent 01's persistent session must actively keep the queue moving while awake. The scheduler task remains highest-priority infrastructure because it eliminates this recurring manual poke.

## Acceptance

This directive is satisfied when:
- current useful READY work is actively executing without another Michael prompt;
- subsequent workers are launched as predecessors finish, within quota/concurrency policy;
- the coordinator stops only on real blockers or when the useful queue is done;
- the required acknowledgement names what was launched and which models were selected.
