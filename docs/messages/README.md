# Aria → Agent 01 durable inbox protocol

**Purpose:** remove Michael from the message-passing loop between Aria and the Business OS coordinator.

## Transport

Aria writes one immutable Markdown message per event to the dedicated branch:

`liaison/aria-to-agent-01`

Path:

`docs/messages/inbox/<message-id>.md`

Agent 01 reads those messages from the remote branch and records disposition on:

`research/agent-01-coordinator`

at:

`docs/messages/acks/<message-id>.md`

This avoids concurrent writes to Agent 01's active branch.

## Message ID

Use:

`ARIA-YYYYMMDD-HHMM-<short-topic>`

Central time when known.

## Required message fields

- ID
- Created
- Sender
- Type
- Source / provenance
- Owner intent
- Facts / observations
- Inference (if any)
- Requested coordinator action
- Safety / authority boundary
- Acceptance / expected durable result

## Types

- OWNER_INPUT
- PROJECT_FACT
- TRAINING_SIGNAL
- TASK_REQUEST
- QUESTION

## Coordinator disposition

An ack must contain:

- message ID
- RECEIVED / INCORPORATED / TASKED / REJECTED / NEEDS_OWNER_DECISION
- why
- affected tasks / ADRs / contracts / files
- commit(s)
- remaining blocker, if any

## Safety

This channel transfers information and project direction. It does not independently authorize spending, purchases, seller/customer contact, publishing, production deployment, or other protected external actions.
