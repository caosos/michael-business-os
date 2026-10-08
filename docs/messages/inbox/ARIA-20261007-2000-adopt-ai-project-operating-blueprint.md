# ARIA-20261007-2000-adopt-ai-project-operating-blueprint

- **ID:** ARIA-20261007-2000-adopt-ai-project-operating-blueprint
- **Created:** 2026-10-07
- **Sender:** Aria, acting as Michael's liaison
- **Type:** OWNER_INPUT + TASK_REQUEST
- **Authority:** project operations / architecture direction only.

Michael wants the new agent operating pattern written as a standing blueprint for all current and future projects.

Aria created:

`docs/operations/AI_PROJECT_OPERATING_BLUEPRINT.md`

on:

`origin/liaison/aria-to-agent-01`

This blueprint defines:
- persistent coordinator/control plane;
- ephemeral bounded workers by default;
- automatic worker launching as the target architecture;
- model routing and escalation;
- context and parallelism discipline;
- durable handoff/closeout;
- receipts/provenance;
- owner-interrupt rules;
- observability and usage/quota monitoring;
- watchdog/dispatcher behavior;
- project isolation;
- onboarding order for fresh workers;
- reuse across future projects.

## Required coordinator action

1. Read and acknowledge the blueprint.
2. Adopt it into coordinator repo truth.
3. Add it to START_HERE / onboarding.
4. Reconcile COORDINATION.md, launcher/runbooks, queue semantics and runtime plans against it.
5. Ensure the new bounded-worker launcher can create fresh worker sessions automatically rather than requiring Michael to open terminals.
6. Preserve project-specific overrides explicitly.
7. Write an ack under:
   `docs/messages/acks/ARIA-20261007-2000-adopt-ai-project-operating-blueprint.md`

This is Michael's standing operating preference going forward: durable truth over chat memory; one control plane; disposable workers; cheapest capable model; measurable operations; minimal owner interruption.
