"""G-08 part 1: adversarial tests of A-15 `workflows.propose_followup` on the REAL runtime (reference, or lane D + lane E via
MBOS_QA_STATE_BACKEND=lane_d MBOS_QA_GATEWAY_MODE=lane_e). Collected only when MBOS_QA_IMPL is set."""
from __future__ import annotations

import importlib
import os
import time

import pytest

IMPL = os.environ.get("MBOS_QA_IMPL", "")
collect_ignore_glob = [] if IMPL else ["test_*.py"]
FLIP = "FIX-TRAILER-1"
ZERO = {"amount": 0, "currency": "USD"}
FU_EMAIL = {"capability": "comms.email.send", "summary": "Follow-up: ask the seller whether the trailer is still available",
            "reversibility": "irreversible", "estimated_cost": ZERO}
FU_UNGRANTED = {"capability": "comms.voice.call", "summary": "Follow-up: phone the seller", "reversibility": "irreversible",
                "estimated_cost": ZERO}


@pytest.fixture(scope="session")
def qa(tmp_path_factory):
    mod, _, fn = IMPL.partition(":")
    q = getattr(importlib.import_module(mod), fn)(tmp_path_factory.mktemp("followup"))
    yield q
    q.close()


def acted_item(qa, listing: str = FLIP) -> tuple[str, dict]:
    """discover → YES (with step-up) → ACTED. Returns (item_id, first ActionRequest)."""
    i = qa.discover(listing)
    a = qa.pending(i)
    qa.decide(a["action_request_id"], "YES")
    assert qa.wait_state(i, {"ACTED", "FAILED"}) == "ACTED"
    return i, a


_DEFAULT = object()


def followup(qa, item_id: str, pa=_DEFAULT):
    from mbos import workflows

    return workflows.propose_followup(item_id, dict(FU_EMAIL) if pa is _DEFAULT else pa)


def live_followups(qa, item_id: str, first_id: str) -> list[dict]:
    return [a for a in qa.areqs(item_id=item_id) if a["action_request_id"] != first_id
            and a["status"] in ("pending_approval", "held", "approved", "executing", "executed")]


def snapshot(qa, item_id: str) -> dict:
    return {"state": qa.item(item_id)["state"], "receipts": len(qa.receipts(item_id=item_id)),
            "areqs": len(qa.areqs(item_id=item_id)), "all_receipts": qa.scalar("SELECT count(*) FROM mbos.receipts")}


def wait_for(cond, timeout=20.0, step=0.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return False
