"""G-05 card acceptance. Two kinds of tests:
  * PURE (no database): adversarial inputs straight into `mbos.card` (installed from the pinned 01 commit). The input
    world is built from the frozen contract examples, so it is always schema-valid except where a test breaks it ON PURPOSE.
  * BACKEND (real runtime): the same checks over real flows on the configured backend (reference, or lane D+E with
    MBOS_QA_STATE_BACKEND=lane_d MBOS_QA_GATEWAY_MODE=lane_e). Collected only when MBOS_QA_IMPL is set.
Validation of every card is INDEPENDENT of 01's `validate_card`: this lane's pinned `ext/card.schema.json` with
format checks on, plus the honesty rules re-implemented here from ADR-0011."""
from __future__ import annotations

import importlib
import itertools
import json
import os
import pathlib

import pytest
from jsonschema import Draft202012Validator

QA = pathlib.Path(__file__).resolve().parents[2]
EX = QA / "contracts" / "examples"
CARD_SCHEMA = json.loads((QA / "ext" / "card.schema.json").read_text())
_V = Draft202012Validator(CARD_SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER)
IMPL = os.environ.get("MBOS_QA_IMPL", "")
collect_ignore_glob = [] if IMPL else ["test_card_backends.py"]

_ALPH = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def pid(n: int) -> str:
    """A valid prov_ ULID-shaped id."""
    s = ""
    for _ in range(26):
        s = _ALPH[n % 32] + s
        n //= 32
    return "prov_" + s


def independent_schema_errors(card: dict) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:160]}" for e in _V.iter_errors(card)]


def base_item(**over) -> dict:
    item = json.loads((EX / "item-flip-trailer.example.json").read_text())
    item["state"] = "RECOMMENDED"
    item.pop("action_request_ids", None)
    item.update(over)
    return item


def receipt(seq: int, type_: str, item_id: str, *, areq: str | None = None, after=None, before=None, intent="x",
            actor="agent-01-coordinator", prov=None, **extra) -> dict:
    r = {"receipt_id": "rcpt_" + pid(seq)[5:], "seq": seq, "ts": f"2026-10-07T12:{seq // 60:02d}:{seq % 60:02d}.000000Z",
         "schema_version": "1.0.0", "type": type_, "actor": {"type": "agent", "id": actor}, "intent": intent,
         "item_id": item_id, "provenance_ids": prov or [pid(1000 + seq)], "idempotency_key": f"k{seq}",
         "prev_hash": None, "row_hash": "sha256:" + "0" * 64}
    if areq:
        r["action_request_id"] = areq
    if after is not None:
        r["after_state"] = after
    if before is not None:
        r["before_state"] = before
    r.update(extra)
    return r


def areq_doc(item_id: str, cap="comms.email.send", status="pending_approval", n=1, **over) -> dict:
    a = json.loads((EX / "action-request-email-held.example.json").read_text())
    a.update({"item_id": item_id, "capability": cap, "status": status,
              "action_request_id": "areq_" + pid(n)[5:], "category": "email" if cap.startswith("comms") else a["category"],
              "payload": {**a["payload"], "summary": "first contact"}})
    a.update(over)
    return a


@pytest.fixture(scope="session")
def mc():
    from mbos_qa import pincheck

    pincheck.require()
    return importlib.import_module("mbos.card")


@pytest.fixture(scope="session")
def profile(mc):
    return mc.load_profile()


def world(item=None, *, state="RECOMMENDED", flow=("DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED"),
          areq_status="pending_approval", cap="comms.email.send"):
    """(item, receipts, areqs): a small, valid, coherent history for one item."""
    item = item or base_item()
    iid = item["item_id"]
    rs, seq = [], 0
    prev = None
    for st in flow:
        seq += 1
        rs.append(receipt(seq, "ITEM_STATE_CHANGED", iid, before={"state": prev} if prev else None, after={"state": st},
                          intent=f"item -> {st}"))
        prev = st
        if st == "SCORED":
            seq += 1
            rs.append(receipt(seq, "SCORE_RECORDED", iid, intent="scored"))
    a = areq_doc(iid, cap=cap, status=areq_status)
    if state in ("AWAITING_APPROVAL", "APPROVED", "ACTED"):
        seq += 1
        rs.append(receipt(seq, "ACTION_PROPOSED", iid, areq=a["action_request_id"], intent="proposed"))
    item = {**item, "state": state}
    return item, rs, [a]


def shuffled(seq, rnd):
    x = list(seq)
    rnd.shuffle(x)
    return x


def leaves(node, path=""):
    """Every datum-shaped dict ({'value': ...}) under a card node, with its path."""
    if isinstance(node, dict):
        if "value" in node:
            yield path, node
        else:
            for k, v in node.items():
                yield from leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from leaves(v, f"{path}[{i}]")


def unknown_paths(card: dict, skip=("activity_trail", "status", "why", "unknowns")) -> set[str]:
    return {p for k, v in card.items() if k not in skip for p, d in leaves(v, k) if d.get("value") == "UNKNOWN"}


CONTROL = {chr(c) for c in itertools.chain(range(0, 9), range(11, 32), [127])}  # tab (9) and newline (10) are layout


# ---------------------------------------------------------------- backend fixtures (only used by test_card_backends.py)
@pytest.fixture(scope="session")
def qa(tmp_path_factory):
    mod, _, fn = IMPL.partition(":")
    q = getattr(importlib.import_module(mod), fn)(tmp_path_factory.mktemp("card"))
    yield q
    q.close()
