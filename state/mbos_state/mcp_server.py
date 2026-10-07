"""State MCP server (D-06): exposes `StateTools` over MCP (stdio by default).

Configuration comes from the process supervisor, never from the model:
  MBOS_DSN            libpq DSN for the server's own login. agent profile: mbos_state_mcp; operator profile:
                      mbos_operator_ui. Agent processes themselves get NO write credentials.
  MBOS_MCP_AGENT_ID   caller identity recorded in provenance and receipts (e.g. agent-02-opportunity)
  MBOS_MCP_PROFILE    agent (default) | operator
  MBOS_MCP_SCOPE      optional comma-separated allow-list of tool names

Run:  python -m mbos_state.mcp_server            (one server process per agent identity)
"""

from __future__ import annotations

import os
import sys
from typing import Any

import psycopg
from mcp.server.mcpserver import MCPServer

from . import __version__
from .mcp_tools import Caller, StateTools

INSTRUCTIONS = (
    "Michael Business OS state spine. Narrow intent tools only; every write is receipted with provenance in one "
    "transaction. All external actions are DRY-RUN. You cannot approve, execute, spend or change governance here: "
    "propose an ActionRequest and Michael decides in the Operator UI."
)


def _args(scope: dict[str, Any]) -> dict[str, Any]:
    """Tool arguments only (locals() inside a closure also holds the captured `tools`)."""
    return {k: v for k, v in scope.items() if k != "tools"}


def build_server(tools: StateTools) -> MCPServer:
    server = MCPServer(name="mbos-state", version=__version__, instructions=INSTRUCTIONS)
    allowed = set(tools.tools())

    def reg(fn):
        if fn.__name__ in allowed:
            server.tool(name=fn.__name__)(fn)

    def get_item(item_id: str) -> dict:
        """Read one Item v1 document (with ledger-derived reference ids) and its version."""
        return tools.call("get_item", {"item_id": item_id})

    def list_items(state: str | None = None, lane: str | None = None, limit: int = 50) -> dict:
        """List items, newest first. lane = flip | service."""
        return tools.call("list_items", {"state": state, "lane": lane, "limit": limit})

    def create_item(item: dict, intent: str, idempotency_key: str, evidence: list[dict] | None = None,
                    evidence_provenance_ids: list[str] | None = None, trace_id: str | None = None) -> dict:
        """Create an Item v1 (state DISCOVERED or NORMALIZED). evidence: provenance for the source/model facts."""
        return tools.call("create_item", _args(locals()))

    def transition_item(item_id: str, to_state: str, intent: str, idempotency_key: str,
                        expected_version: int | None = None, evidence: list[dict] | None = None,
                        evidence_provenance_ids: list[str] | None = None, trace_id: str | None = None) -> dict:
        """Move an item along the ADR-0004 state machine (illegal moves are refused)."""
        return tools.call("transition_item", _args(locals()))

    def patch_item(item_id: str, patch: dict, intent: str, idempotency_key: str,
                   receipt_type: str = "ITEM_STATE_CHANGED", expected_version: int | None = None,
                   evidence: list[dict] | None = None, evidence_provenance_ids: list[str] | None = None,
                   trace_id: str | None = None) -> dict:
        """Merge top-level document fields (normalized, research, economics, scores, recommendation, sources).
        receipt_type: ITEM_STATE_CHANGED | SCORE_RECORDED | RECOMMENDATION_RECORDED. State changes use transition_item."""
        return tools.call("patch_item", _args(locals()))

    def propose_action(action_request: dict, intent: str, idempotency_key: str, evidence: list[dict] | None = None,
                       evidence_provenance_ids: list[str] | None = None, trace_id: str | None = None) -> dict:
        """Propose one side effect as an ActionRequest (status drafted). It executes only after Michael's YES."""
        return tools.call("propose_action", _args(locals()))

    def record_outcome(outcome: dict, intent: str, idempotency_key: str, evidence: list[dict] | None = None,
                       evidence_provenance_ids: list[str] | None = None, trace_id: str | None = None) -> dict:
        """Record what actually happened (Outcome v1) for LEARN."""
        return tools.call("record_outcome", _args(locals()))

    def record_lesson(lesson: dict, intent: str, idempotency_key: str, evidence: list[dict] | None = None,
                      evidence_provenance_ids: list[str] | None = None, trace_id: str | None = None) -> dict:
        """Record a durable lesson (scope, statement, basis); config changes it proposes still need approval."""
        return tools.call("record_lesson", _args(locals()))

    def record_approval(approval: dict, intent: str, idempotency_key: str, trace_id: str | None = None) -> dict:
        """OPERATOR PROFILE ONLY: record Michael's YES / NO / MODIFY / HOLD made in the Operator UI."""
        return tools.call("record_approval", _args(locals()))

    for fn in (get_item, list_items, create_item, transition_item, patch_item, propose_action, record_outcome,
               record_lesson, record_approval):
        reg(fn)
    return server


def tools_from_env(env: dict[str, str] = os.environ) -> StateTools:
    scope = env.get("MBOS_MCP_SCOPE")
    caller = Caller(agent_id=env["MBOS_MCP_AGENT_ID"], profile=env.get("MBOS_MCP_PROFILE", "agent"),
                    scope=frozenset(s.strip() for s in scope.split(",") if s.strip()) if scope else None)
    return StateTools(psycopg.connect(env["MBOS_DSN"], autocommit=True), caller)


def main() -> int:
    for var in ("MBOS_DSN", "MBOS_MCP_AGENT_ID"):
        if not os.environ.get(var):
            print(f"error: set ${var}", file=sys.stderr)
            return 2
    build_server(tools_from_env()).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
