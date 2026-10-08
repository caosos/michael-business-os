# ARIA-20261007-1945-agent-runtime-efficiency-and-metrics

- **ID:** ARIA-20261007-1945-agent-runtime-efficiency-and-metrics
- **Created:** 2026-10-07
- **Sender:** Aria, acting as Michael's liaison
- **Type:** OWNER_INPUT + TASK_REQUEST + RESEARCH_SUMMARY
- **Authority:** architecture/runtime/observability direction only. No live external contact, spend, publishing, bidding, payment, deployment, or unsafe host mutation is authorized by this message.

## Michael's current direction

Michael agrees the current 7-long-lived-Claude-session pattern is inefficient and wants it redesigned now.

Goals:
1. Close out long-running specialist sessions safely.
2. Preserve every lane's durable state so future workers can take over cold.
3. Keep only the small number of persistent sessions that materially benefit from continuity.
4. Convert specialist execution to short-lived/bounded workers or subagents.
5. Use the best available Claude model for each class of work.
6. Use Fable strategically instead of leaving that pool unused.
7. Continuously monitor Claude usage/efficiency in the Michael OS dashboard.

## Observed account/runtime facts from Michael's Claude Code UI

Michael is logged into Claude Code with his Claude Max account.

Observed 2026-10-07:
- current session/window: 75% used
- current week all models: 38% used
- current week Fable: 0% used
- 91% of usage was at >150k context
- 89% of usage occurred while 4+ sessions ran in parallel
- 21% of usage came from subagent-heavy sessions
- auto-compaction enabled
- "Continue automatically at usage limit" enabled
- dynamic workflows enabled
- auto mode server enabled
- artifacts enabled
- checkpoints/rewind enabled
- current interactive sessions are using Sonnet 5.5

These metrics strongly indicate that context length and parallel long-lived sessions are wasting Max-plan capacity.

## External research summary

Research checked against current Anthropic documentation on 2026-10-07:

### Max / usage
- Max usage is shared across Claude surfaces and Claude Code and includes both a rolling session window and weekly limits.
- Long conversations, attachments, tool use, model choice, effort and artifacts all affect usage.
- Anthropic explicitly recommends using `/compact` or `/clear` for long sessions.
- Current docs state Max 5x and Max 20x reset session allowance every five hours; weekly limits also apply.

### Model strategy
- Claude Code docs recommend using `/model` to inspect/switch available models.
- Anthropic explicitly recommends "plan with Opus, execute with Sonnet" for complex coding; `/model opusplan` implements that pattern where available.
- Fable 5.1 is Anthropic's most capable generally available model and is positioned for ambitious, long-running, asynchronous work.
- Fable is appropriate for the hardest architecture/integration/research jobs, not routine implementation.
- Opus 5.5 is strong enough for most difficult work and should be considered before escalating to Fable if the task does not justify the heavier model.
- Sonnet 5.x should remain the default bounded implementation worker.

### Agentic execution
- Anthropic recommends using subagents when tasks are parallel, isolated, or independent, not for simple sequential work.
- Long-horizon work should persist state externally (git/files) and continue across fresh context windows.
- Claude Code non-interactive mode supports `claude -p` with `--output-format json` or `stream-json`.
- JSON output includes session metadata such as duration, API duration, turn count, session id and computed cost, making it suitable for worker telemetry.
- Claude supports resuming a session by id when continuity is genuinely needed.

### Durable state
- Anthropic recommends git for state tracking and structured files for machine state.
- This aligns with Michael OS's existing repo-truth/receipt model.

## Required architecture change

### Persistent control plane
Keep persistent only:
- Agent 01 coordinator/foreman
- optionally Agent 07 QA during active release/hardening windows

Do NOT keep Agents 02-06 as permanently accumulating conversations merely because their lane exists.

### Ephemeral worker model
For each bounded task:
1. Agent 01 chooses lane + task + model.
2. Spawn a fresh worker/subagent with only:
   - START_HERE.md
   - docs/product/DEAL_SNIFFER_START_HERE.md
   - docs/COORDINATION.md
   - task record
   - lane-specific AGENT_STATUS / relevant ADRs / targeted files
3. Worker claims the task.
4. Worker implements/tests.
5. Worker writes receipt/status/commit.
6. Worker exits.
7. Future workers continue from repo truth, not inherited chat context.

Resume an old session only when its private working context is genuinely valuable and still compact. Otherwise start fresh.

## Model router policy to design

Create a documented router, with defaults roughly:

- **Sonnet 5.x** — default implementation, tests, adapters, docs, routine refactors, bounded research.
- **Opus 5.5 / opusplan where available** — complex planning, cross-lane architecture, difficult debugging, high-risk integration review.
- **Fable 5.1** — hardest long-horizon asynchronous work, large-codebase architecture/migrations, major product synthesis, deep research where it materially outperforms other choices.
- **lighter/cheaper model if available** — repetitive low-risk classification/extraction tasks.

Do not hard-code unsupported model aliases. Use `/model` / supported CLI model identifiers from the installed Claude Code version.

Routing decisions should become receipts/telemetry:
- task id
- selected model
- reason
- start/end
- duration
- turns
- context/usage metadata when available
- result
- retries/escalations

## Safe closeout of current long-lived workers

Before terminating a current specialist session:
1. fetch latest coordinator truth;
2. finish or stop at a clean task boundary;
3. commit/push all valid code;
4. update AGENT_STATUS accurately;
5. write receipts for completed consequential work;
6. move unfinished work to READY_QUEUE with acceptance criteria;
7. write a compact lane handoff identifying:
   - current head
   - completed work
   - outstanding tasks
   - blockers
   - key files
   - tests/run commands
   - known pitfalls
8. verify clean/intentional git status;
9. only then close that Claude session/tmux worker.

Do not delete worktrees/branches during this migration.

## Usage / efficiency dashboard requirement

Michael wants Claude-agent usage visible in the Operator UI dashboard.

Create an observability lane/task set that exposes, at minimum:

### Supported local worker telemetry
For every future non-interactive worker run, collect from Claude Code supported JSON/stream-json output where available:
- session_id
- model
- task id
- start/end
- duration
- API duration
- number of turns
- computed cost field if returned
- success/error
- retry/escalation count

### Swarm/runtime metrics
- active workers
- queued tasks
- blocked tasks
- idle/persistent sessions
- task throughput/day
- average worker duration
- model mix
- Fable/Opus/Sonnet task counts
- context-management events
- stale worker/session alerts

### Max-plan quota metrics
Michael's Claude UI currently exposes session-window %, weekly all-model %, Fable %, reset times and contributors such as >150k-context and 4+ parallel-session percentages.

Investigate whether the installed Claude Code version exposes these values through a supported local command/file/API suitable for automation.

Rules:
- Prefer documented/supported local interfaces.
- Do NOT scrape private Anthropic endpoints or reverse-engineer authentication.
- If exact Max-plan quota percentages are not programmatically available, clearly mark them manual/UNKNOWN and build the dashboard so supported telemetry still works now.
- A manual snapshot entry is acceptable as an interim fallback.
- Do not mislabel Claude Code's computed dollar-cost estimate as an actual separate bill when authenticated through Max.

## Efficiency policies to encode

- Avoid >150k contexts unless the task truly benefits.
- Fresh worker by default for a new bounded task.
- `/compact` when continuing a context is justified.
- `/clear` when changing unrelated tasks.
- Limit simultaneous heavyweight workers; parallelism is for independent work with proven benefit.
- Subagents are for isolated parallel workstreams, not every small step.
- Keep durable knowledge in repo truth rather than chat.
- Use Fable deliberately for high-value difficult jobs instead of leaving the pool unused, while not wasting it on routine work.
- Measure output per usage window, not agent count.

## Required Agent 01 actions

1. Acknowledge this message durably.
2. Create a migration plan and bounded READY tasks.
3. Close out Agents 02-06 safely under the closeout checklist.
4. Preserve Agent 01; decide whether QA stays persistent.
5. Implement/commission a bounded-worker launcher based on supported Claude Code non-interactive mode and JSON telemetry.
6. Add a model-router policy and receipts.
7. Add usage/agent telemetry to the Operator UI.
8. Investigate supported access to the Max-plan quota percentages shown in Claude's Usage screen.
9. Amend START_HERE / COORDINATION / launcher docs so future agents use the new architecture.
10. Keep all current external-action DRY-RUN boundaries unchanged.

## Acceptance

Complete when:
- no specialist knowledge depends on an old chat/tmux context;
- current specialist sessions can be closed without losing state;
- coordinator can launch a fresh bounded worker from repo truth;
- one test worker completes a real queued task, records JSON telemetry, commits, and exits;
- model routing is documented and testable;
- dashboard shows supported agent/runtime/model telemetry;
- unsupported quota fields are explicitly UNKNOWN/manual rather than fabricated;
- required ack exists under docs/messages/acks/.
