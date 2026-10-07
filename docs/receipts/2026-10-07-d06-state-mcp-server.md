# Receipt: D-06 (State MCP server, the only agent write path)

- Timestamp: 2026-10-07T17:43:20Z
- Agent: 04
- Task: READY_QUEUE D-06 (queue @ aa88e7a), assigned by Agent 01.
- Inputs: ADR-0003 (MCP tool boundary), the queue acceptance criteria, and this lane's `mbos.*` SQL API (migrations 0000–0007).
- Dependency added to `state/.venv`: `mcp` 2.3.0, the official Python MCP SDK, pinned `>=2.3,<3`. No other lane pins MCP.

## Built
- `state/migrations/0008_mcp_calls.sql`: append-only `mbos.mcp_calls`. An "ok" write row must cite ≥1 existing receipt (CHECK + trigger).
- `state/mbos_state/mcp_tools.py`: the transport-free tool layer.
- `state/mbos_state/mcp_server.py`: an MCP 2.x `MCPServer` over stdio.
- `state/tests/test_mcp.py`: 13 tests, including a real subprocess server driven over stdio by the MCP client.

## Decision, flagged for Agent 01
The queue lists "record approval" among the tools. It is exposed **only** in the `operator` profile:
- intended for the non-LLM Operator UI backend
- uses the `mbos_operator_ui` login, chosen by the process supervisor

The `agent` profile does not even list it. The DB role `agent_write` cannot approve either way.

## Acceptance (FACT)
- **"An agent role without the MCP cannot write":** `test_agent_without_the_mcp_cannot_write` has the agent credential `mbos_reader` try:
  - `mbos.create_item`
  - direct INSERTs into items and provenance
  - `append_receipt`
  - an INSERT into mcp_calls

  All fail with `InsufficientPrivilege`. Separately, the MCP's own role cannot approve, execute, spend, change PANIC or claim effectors.
- **"Every tool call is receipted":**
  - Every successful write call in an end-to-end flow (create, 5 transitions, patch, propose, outcome) has receipts.
  - Each of those receipts cites the call's provenance, and its actor is the caller.
  - Reads, refusals and errors are logged in `mcp_calls` and change no state (counts are unchanged).
  - The DB refuses an "ok" write log without receipts.
- **Identity:**
  - `proposed_by` spoofing is ignored.
  - Evidence carrying `human_actor`, `approval_id` or actor_type human is refused.
  - Scope allow-lists apply at registration (the stdio client never sees out-of-scope tools) and again at the call.
- **Injection:** SQL strings in arguments are stored as data; `verify_chain` OK.
- `pytest`: 162 passed (the full suite had already passed twice at 161 before the stdio test was added).
