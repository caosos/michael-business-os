"""State MCP tool layer (D-06, ADR-0003): the ONLY agent write path into the state spine.

Transport-free so it can be tested directly; `mcp_server.py` exposes it over MCP.

Guarantees:
- **Caller identity and scope** come from the server process (`Caller`), never from tool arguments. Each
  call's provenance row records agent_id, profile, scope and the MBOS-CJSON-1 hash of the arguments.
- **Narrow intent tools only.** Every write goes through an `mbos.*` SQL function. No tool takes SQL, and
  values are always bound parameters.
- **Every write call is receipted.** The state change, its receipt(s) and the `mcp_calls` audit row commit in
  one transaction, and `mcp_calls` refuses an "ok" write row without receipts. Reads and refused or failed
  calls are logged in `mcp_calls` too; they change no state.
- **Least privilege.** The `agent` profile connects as `mbos_state_mcp` (agent_write) and has no approval,
  execution, budget or PANIC capability. The `operator` profile (non-LLM Operator UI backend only) connects
  as `mbos_operator_ui` (approver) and adds `record_approval`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

import psycopg
from psycopg.types.json import Jsonb

from . import __version__, mbos_canonical

READ_TOOLS = ("get_item", "list_items")
AGENT_WRITE_TOOLS = ("create_item", "transition_item", "patch_item", "propose_action", "record_outcome", "record_lesson")
OPERATOR_WRITE_TOOLS = ("record_approval",)
PATCH_RECEIPT_TYPES = ("ITEM_STATE_CHANGED", "SCORE_RECORDED", "RECOMMENDATION_RECORDED")
EVIDENCE_FIELDS = {"basis", "source_uri", "fetched_at", "model_id", "model_version", "prompt_hash", "tool_name",
                   "tool_version", "config_version", "trace_id", "inputs_used", "derived_from", "confidence",
                   "actor_type"}


class ToolRefused(Exception):
    """The call was rejected before touching state (scope, validation)."""


class ToolFailed(Exception):
    """The database refused the call; nothing was written. `code` is the SQLSTATE."""

    def __init__(self, code: str | None, message: str):
        super().__init__(f"{code}: {message}" if code else message)
        self.code = code


@dataclass(frozen=True)
class Caller:
    agent_id: str
    profile: str = "agent"                      # agent | operator
    scope: frozenset[str] | None = None         # None = every tool of the profile

    def __post_init__(self):
        if not self.agent_id.strip():
            raise ValueError("caller agent_id is required")
        if self.profile not in ("agent", "operator"):
            raise ValueError(f"unknown profile {self.profile!r}")


@dataclass
class StateTools:
    conn: psycopg.Connection                    # autocommit connection; each call opens its own transaction
    caller: Caller
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- catalogue ------------------------------------------------------------
    def tools(self) -> list[str]:
        names = list(READ_TOOLS) + list(AGENT_WRITE_TOOLS)
        if self.caller.profile == "operator":
            names += list(OPERATOR_WRITE_TOOLS)
        if self.caller.scope is not None:
            names = [n for n in names if n in self.caller.scope]
        return names

    # -- dispatch ---------------------------------------------------------------
    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        args = {k: v for k, v in args.items() if v is not None}
        kind = "read" if tool in READ_TOOLS else "write"
        try:
            args_hash = mbos_canonical.sha256_of(args)
        except mbos_canonical.CanonicalError as e:
            args_hash = mbos_canonical.sha256_of({"unhashable_arguments": str(e)})
            self._log_failure(tool, kind, args_hash, "refused", "MCP400", f"arguments not MBOS-CJSON-1: {e}")
            raise ToolRefused(f"arguments are not valid MBOS-CJSON-1 JSON: {e}") from e
        if tool not in self.tools():
            self._log_failure(tool, kind, args_hash, "refused", "MCP403",
                              f"tool {tool!r} is not in scope for {self.caller.agent_id} ({self.caller.profile})")
            raise ToolRefused(f"tool {tool!r} is not available to {self.caller.agent_id}")
        handler: Callable = getattr(self, f"_t_{tool}")
        with self._lock:
            try:
                with self.conn.transaction():
                    if kind == "read":
                        result = handler(args)
                        self._log(tool, kind, args_hash, "ok", None, [])
                        return result
                    prov = self._call_provenance(tool, args_hash, args.get("trace_id"))
                    evidence = self._evidence(args)
                    result, idem = handler(args, [prov] + evidence)
                    receipt_ids, replayed = self._receipts(idem)
                    self._log(tool, kind, args_hash, "replayed" if replayed else "ok", prov, receipt_ids)
                return {**result, "receipt_ids": receipt_ids, "provenance_id": prov, "replayed": replayed}
            except ToolRefused as e:
                self._log_failure(tool, kind, args_hash, "refused", "MCP400", str(e))
                raise
            except psycopg.Error as e:
                msg = (e.diag.message_primary or str(e)).strip()
                self._log_failure(tool, kind, args_hash, "error", e.sqlstate, msg)
                raise ToolFailed(e.sqlstate, msg) from e

    # -- helpers ------------------------------------------------------------------
    def _one(self, sql: str, params: tuple) -> Any:
        return self.conn.execute(sql, params).fetchone()[0]

    def _actor(self) -> Jsonb:
        return Jsonb({"type": "agent" if self.caller.profile == "agent" else "system", "id": self.caller.agent_id})

    def _call_provenance(self, tool: str, args_hash: str, trace_id: str | None) -> str:
        scope = sorted(self.caller.scope) if self.caller.scope is not None else ["*"]
        return self._one("SELECT mbos.record_provenance(%s)", (Jsonb({
            "actor_type": "agent" if self.caller.profile == "agent" else "system",
            "agent_name": self.caller.agent_id, "basis": "FACT",
            "tool_name": f"mbos-state-mcp/{tool}", "tool_version": __version__,
            "trace_id": trace_id,
            "inputs_used": [{"ref": "mcp:arguments", "hash": args_hash},
                            {"ref": "mcp:caller", "agent_id": self.caller.agent_id,
                             "profile": self.caller.profile, "scope": scope}],
        }),))

    def _evidence(self, args: dict) -> list[str]:
        """Inline evidence provenance (sources, models). Identity is forced; human/approval provenance is
        never accepted from an agent."""
        ids = list(args.get("evidence_provenance_ids") or [])
        for ev in args.get("evidence") or []:
            extra = set(ev) - EVIDENCE_FIELDS
            if extra:
                raise ToolRefused(f"evidence fields not allowed: {sorted(extra)}")
            actor_type = ev.get("actor_type") or ("external" if ev.get("source_uri") else "agent")
            if actor_type not in ("agent", "external"):
                raise ToolRefused("evidence actor_type must be agent or external")
            ids.append(self._one("SELECT mbos.record_provenance(%s)",
                                 (Jsonb({**ev, "actor_type": actor_type, "agent_name": self.caller.agent_id}),)))
        return ids

    def _receipts(self, idem: str) -> tuple[list[str], bool]:
        rows = [r[0] for r in self.conn.execute(
            "SELECT receipt_id FROM mbos.receipts WHERE tx_id = pg_current_xact_id() ORDER BY seq")]
        if rows:
            return rows, False
        row = self.conn.execute("SELECT receipt_id FROM mbos.receipts WHERE idempotency_key = %s", (idem,)).fetchone()
        return ([row[0]] if row else []), True

    def _log(self, tool, kind, args_hash, outcome, prov, receipt_ids, code=None, error=None):
        self.conn.execute(
            """INSERT INTO mbos.mcp_calls (agent_id, profile, tool, tool_kind, args_hash, outcome, error_code, error,
                                           provenance_id, receipt_ids)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.caller.agent_id, self.caller.profile, tool, kind, args_hash, outcome, code, error, prov, receipt_ids))

    def _log_failure(self, tool, kind, args_hash, outcome, code, error):
        with self.conn.transaction():
            self._log(tool, kind, args_hash, outcome, None, [], code, error[:2000])

    @staticmethod
    def _need(args: dict, *keys: str) -> None:
        missing = [k for k in keys if k not in args or args[k] in ("", None)]
        if missing:
            raise ToolRefused(f"missing required argument(s): {missing}")

    # -- read tools -----------------------------------------------------------------
    def _t_get_item(self, a: dict) -> dict:
        self._need(a, "item_id")
        row = self.conn.execute("SELECT version, doc FROM mbos.v_item_documents WHERE item_id = %s",
                                (a["item_id"],)).fetchone()
        if row is None:
            raise ToolRefused(f"item {a['item_id']} not found")
        return {"item_id": a["item_id"], "version": row[0], "item": row[1]}

    def _t_list_items(self, a: dict) -> dict:
        limit = max(1, min(int(a.get("limit", 50)), 500))
        rows = self.conn.execute(
            """SELECT item_id, type, category, state, version, updated_at FROM mbos.items
               WHERE (%s::text IS NULL OR state = %s) AND (%s::text IS NULL OR type = %s)
               ORDER BY updated_at DESC LIMIT %s""",
            (a.get("state"), a.get("state"), a.get("lane"), a.get("lane"), limit)).fetchall()
        return {"items": [{"item_id": r[0], "lane": r[1], "category": r[2], "state": r[3], "version": r[4],
                           "updated_at": r[5].isoformat()} for r in rows]}

    # -- write tools (return (result, idempotency_key)) -----------------------------
    def _t_create_item(self, a: dict, prov: list[str]):
        self._need(a, "item", "intent", "idempotency_key")
        item_id = self._one("SELECT mbos.create_item(%s,%s,%s,%s,%s)",
                            (Jsonb(a["item"]), self._actor(), a["intent"], prov, a["idempotency_key"]))
        return {"item_id": item_id}, a["idempotency_key"]

    def _t_transition_item(self, a: dict, prov: list[str]):
        self._need(a, "item_id", "to_state", "intent", "idempotency_key")
        rid = self._one("SELECT mbos.transition_item(%s,%s,%s,%s,%s,%s,%s)",
                        (a["item_id"], a["to_state"], self._actor(), a["intent"], prov, a["idempotency_key"],
                         a.get("expected_version")))
        return {"item_id": a["item_id"], "to_state": a["to_state"], "receipt_id": rid}, a["idempotency_key"]

    def _t_patch_item(self, a: dict, prov: list[str]):
        self._need(a, "item_id", "patch", "intent", "idempotency_key")
        rtype = a.get("receipt_type", "ITEM_STATE_CHANGED")
        if rtype not in PATCH_RECEIPT_TYPES:
            raise ToolRefused(f"receipt_type must be one of {PATCH_RECEIPT_TYPES}")
        rid = self._one("SELECT mbos.update_item_doc(%s,%s,%s,%s,%s,%s,%s,%s)",
                        (a["item_id"], Jsonb(a["patch"]), rtype, self._actor(), a["intent"], prov,
                         a["idempotency_key"], a.get("expected_version")))
        return {"item_id": a["item_id"], "receipt_id": rid}, a["idempotency_key"]

    def _t_propose_action(self, a: dict, prov: list[str]):
        self._need(a, "action_request", "intent", "idempotency_key")
        areq = {**a["action_request"], "proposed_by": self.caller.agent_id,           # identity is not an argument
                "provenance_ids": prov + list(a["action_request"].get("provenance_ids") or [])}
        areq.pop("status", None)
        areq_id = self._one("SELECT mbos.propose_action(%s,%s,%s,%s)",
                            (Jsonb(areq), self._actor(), a["intent"], a["idempotency_key"]))
        return {"action_request_id": areq_id, "status": "drafted"}, a["idempotency_key"]

    def _t_record_outcome(self, a: dict, prov: list[str]):
        self._need(a, "outcome", "intent", "idempotency_key")
        outcome = {**a["outcome"], "provenance_ids": prov + list(a["outcome"].get("provenance_ids") or [])}
        oid = self._one("SELECT mbos.record_outcome(%s,%s,%s,%s)",
                        (Jsonb(outcome), self._actor(), a["intent"], a["idempotency_key"]))
        return {"outcome_id": oid}, a["idempotency_key"]

    def _t_record_lesson(self, a: dict, prov: list[str]):
        self._need(a, "lesson", "intent", "idempotency_key")
        lesson = {**a["lesson"], "provenance_ids": prov + list(a["lesson"].get("provenance_ids") or [])}
        lid = self._one("SELECT mbos.record_lesson(%s,%s,%s,%s)",
                        (Jsonb(lesson), self._actor(), a["intent"], a["idempotency_key"]))
        return {"lesson_id": lid}, a["idempotency_key"]

    def _t_record_approval(self, a: dict, prov: list[str]):
        """Operator profile only: records Michael's decision made in the Operator UI."""
        self._need(a, "approval", "intent", "idempotency_key")
        decider = a["approval"].get("decider") or "michael"
        appr = self._one("SELECT mbos.record_approval(%s,%s,%s,%s,%s)",
                         (Jsonb(a["approval"]), Jsonb({"type": "human", "id": decider}), a["intent"],
                          a["idempotency_key"], prov))
        return {"approval_id": appr}, a["idempotency_key"]
