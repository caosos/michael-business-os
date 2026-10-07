# Operator-note store (D-17)

Michael's own mechanic knowledge, the first knowledge source on the Deal Sniffer card.
- **Spec:** Agent 03, `docs/research/agent-03-model-knowledge-source-plan.md` §7.
- **Ruling (Agent 01):** Option A, with no contract change. `OPERATOR_NOTE_RECORDED` is queued for ADR-0009 item 12.
- **Migration:** `state/migrations/0016_operator_notes.sql`.

## What is enforced in the database
| Rule | Mechanism |
|---|---|
| A note names a model: every match group has BOTH non-empty `makes` AND `models` | CHECK `mbos.valid_note_match(match)` |
| `category` is a flip category; `kind` is one of the six kinds | CHECK IN (...) |
| `statement` is 1 to 600 characters; `plan_hint` is at most 600 | CHECK |
| `entered_by` and `basis_of_knowledge` are present; `entered_at` is `timestamptz` | NOT NULL + CHECK |
| `reference_url` is https only | CHECK `LIKE 'https://_%'` |
| `basis` is always RECOMMENDATION (never FACT); the entry function **refuses** anything else rather than rewriting it | CHECK + function |
| `note_id` is `mn_` + 26 Crockford characters | CHECK |
| Human provenance first: `actor_type` human, `human_actor` set, `tool_name` and `tool_version` set, basis RECOMMENDATION; `entered_by` equals its `human_actor`; one provenance row backs one note | BEFORE INSERT trigger |
| The receipt is in the **same transaction**: LESSON_RECORDED, `entity_type` "operator_note", citing that provenance | deferred constraint trigger (no receipt, no commit) |
| Insert-only; an edit or retraction is a new row linked by `supersedes`. A chain cannot fork (UNIQUE), a retracted note cannot be edited, and an edit cannot predate what it replaces | trigger + UNIQUE |
| Only the human channel inserts (the Operator UI, role `approver`); every other role reads | grants |

The elementary-advice lint stays in Python (Agent 03's loader), as agreed.

## API
- `mbos.record_operator_note(bundle jsonb)`: the bundle is exactly what `mbos_economics.new_manual_note()` returns, `{"note", "provenance"}`.
  - It inserts the provenance, then the note, then the receipt, in one transaction.
  - It is replay-safe on `note_id`.
  - An edit is the same call with `note.supersedes` set to the current head.
- `mbos.retract_operator_note(note_id, entered_by, entered_at, reason)`:
  - It resolves to the chain head and inserts a row that copies the head's content with `retracted = true`, so the folded document stays valid.
  - It has its own human provenance and its own receipt.
- Python: `StateStore.record_operator_note` / `retract_operator_note` / `operator_notes_document`.

## Reading
- `mbos.v_operator_notes_current`: the head of each chain, plus a `revisions` count.
- `mbos.operator_notes_document(include_retracted := true)` returns the flat document `{"notes_format": 1, "notes": [...]}`.
  - The latest row of each chain wins.
  - A retraction head renders `"retracted": true`.
  - The `note_id` shown is the head's.
  - Notes are ordered by `entered_at` and `note_id`.

## Acceptance (FACT)
- **A database-rendered document passes Agent 03's real loader.**
  - `python -m mbos_economics note check FILE` exits 0 on the output of `operator_notes_document()`.
  - That includes edits, a retraction, an optional `plan_hint`, a `reference_url` and a `review_after`.
  - `load_manual_notes` returns exactly the live notes.
  - The test builds its notes with the real `new_manual_note()`.
  - It runs when `MBOS_ECONOMICS_SRC` points at Agent 03's `economics/src`, and it is skipped otherwise. Always-on mirror checks cover the same rules.
- The insert-only trigger holds for the owner and a superuser.
- Agent roles (`agent_read`, `agent_write` including the State MCP, `gateway`, `policy_admin`, `outbox_relay`) cannot insert or retract.
- The receipt and the provenance are in the same transaction as the note. A failed note leaves no provenance and no receipt behind. A note row without its receipt cannot commit.

## Residual (UNKNOWN / for Agent 01 and 06)
- `entered_by` is tied to the provenance, not to a login. All humans share the single `mbos_operator_ui` database login, so the Operator UI must pass the authenticated author. The DB cannot tell two humans apart.
- `mbos_dbos` is a member of `approver` (it records Michael's decisions via `spine.decide`), so it **can** call the entry function. Keep the note-entry path in the Operator UI and do not expose it to workflows or LLM-reachable tools. The State MCP `agent` profile has no note tool.
