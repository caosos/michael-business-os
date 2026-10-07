"""B-04, lane E half: apply discovery freeze requests (mbos.discovery.freeze_request/1) as L2 PANIC.

Decision (Agent 05, 2026-10-07): lane E AUTO-APPLIES valid requests.
  * Engaging a freeze is always the safe direction, and discovery has already frozen the source
    locally, so a human in the loop would only add delay.
  * Agents never write PANIC state (0007: agents get no panic_set). The gateway applies the
    request with the requester recorded as the actor, so the receipt shows who asked.
  * RELEASE stays human-only (`mbos-gov panic release --level L2 --target <capability> --actor michael`).

Applying a request is strict, and any problem means the request is refused and nothing is applied:
the request must pass the schema; the capability must equal "discovery.source.<source>.read";
level must be L2; requested_by must be agent-02-opportunity; and only a discovery.source.* target is
accepted, so a request can never freeze or touch another lane. Applying is idempotent: a capability
that is already frozen is skipped (no duplicate revisions).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_ID = "mbos.discovery.freeze_request/1"
REQUESTER = "agent-02-opportunity"


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(resources.files("mbos_governance.schemas").joinpath("freeze-request.schema.json").read_text("utf-8"))
    return Draft202012Validator(schema)


@dataclass
class FreezeOutcome:
    applied: bool
    capability: str | None
    reasons: list[str] = field(default_factory=list)


def problems(req: object) -> list[str]:
    if not isinstance(req, dict):
        return ["NOT_AN_OBJECT"]
    p = [f"SCHEMA:{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:120]}" for e in _validator().iter_errors(req)]
    if not p and req["capability"] != f"discovery.source.{req['source']}.read":
        p.append("CAPABILITY_SOURCE_MISMATCH")
    return p


def apply_freeze_request(gateway, req: dict) -> FreezeOutcome:
    """Validate and apply one request via the gateway (receipted KILL_SWITCH_CHANGED)."""
    bad = problems(req)
    if bad:
        return FreezeOutcome(False, req.get("capability") if isinstance(req, dict) else None, bad)
    cap = req["capability"]
    state = gateway.panic.read()
    if state.readable and cap in state.frozen_capabilities:
        return FreezeOutcome(False, cap, ["ALREADY_FROZEN"])
    ev = req["evidence"]
    reason = (f"{req['reason']} [freeze_request {SCHEMA_ID}; source={req['source']}; evidence={ev['kind']}"
              f"/{ev.get('status')}x{ev['consecutive_blocks']}; requested_at={req['requested_at']}]")
    gateway.engage_panic("L2", cap, actor=req["requested_by"], reason=reason)
    return FreezeOutcome(True, cap, [])


def apply_side_channel(gateway, jsonl_path: str | Path) -> list[FreezeOutcome]:
    """Apply every `{"kind": "freeze_request", "freeze_request": {...}}` line of lane B's side channel.
    Unparsable lines and other kinds are skipped; a bad request is reported, never applied."""
    out: list[FreezeOutcome] = []
    path = Path(jsonl_path)
    if not path.exists():
        return out
    for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            out.append(FreezeOutcome(False, None, [f"LINE_{n}_UNPARSABLE"]))
            continue
        if isinstance(ev, dict) and ev.get("kind") == "freeze_request":
            out.append(apply_freeze_request(gateway, ev.get("freeze_request")))
    return out
