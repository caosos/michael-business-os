"""F-08: follow-up and BINDING offer/quote drafts as their own step-up ActionRequests. Nothing auto-sends."""

from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

import comms_spec as cs
from comms_spec.effector import CommsDryRunEffector
from comms_spec.planner import CommsActionPlanner
from mbos import spine
from mbos.ledger import tool_provenance
from mbos.runtime import components

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "docs/research/contracts/examples"
NOON_AR = datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc)
P = CommsActionPlanner()


def flip():
    return json.loads((EX / "item-flip-trailer.example.json").read_text())


def service():
    it = json.loads((EX / "item-service-drywall.example.json").read_text())
    it["recommendation"]["verdict"] = "YES"
    return it


def q(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(sa.text(sql), p).all()


# ---------------------------------------------------------------- pure planner rules
def test_offer_is_binding_offer_category_step_up():
    (pa,) = P.plan_offer(flip(), 1000, "Saturday morning", "Sunday 6pm")
    c = pa["comms"]
    assert pa["capability"] == "offer.email.send" and pa["reversibility"] == "irreversible"
    assert c["is_binding"] is True and c["template_id"] == "seller_offer" and "$1,000 cash" in c["body"]
    assert c["constraints"] == {**c["constraints"], "tier": 0, "step_up": True, "category": "offer"}
    assert pa["summary"].startswith("BINDING OFFER") and c["template_approval"] == "draft"


@pytest.mark.parametrize("amount", [1500, 0, -5, True, "900", float("nan")])
def test_offer_guards(amount):
    with pytest.raises(ValueError):
        P.plan_offer(flip(), amount, "Saturday", "Sunday")


def test_offer_and_quote_lanes():
    with pytest.raises(ValueError, match="flips"):
        P.plan_offer(service(), 100, "x", "y")
    with pytest.raises(ValueError, match="services"):
        P.plan_quote(flip(), 100, "x", 25, "y")
    with pytest.raises(ValueError, match="deposit"):
        P.plan_quote(service(), 450, "two patches", 80, "Friday")


def test_quote_is_binding():
    (pa,) = P.plan_quote(service(), 450, "two 12in patches + texture match", 25, "Friday")
    assert pa["capability"] == "offer.email.send" and pa["comms"]["is_binding"] is True
    assert "$450" in pa["comms"]["body"] and "25% deposit" in pa["comms"]["body"]


def test_followups_walk_the_question_set():
    qs = [q_["id"] for q_ in cs.questions("flip", "trailer")]
    (f1,) = P.plan_followup(flip(), asked=qs[:2])
    assert f1["comms"]["question_ids"] == qs[2:4] and f1["comms"]["is_binding"] is False
    assert f1["capability"] == "comms.email.send" and f1["comms"]["first_message"] is False
    assert P.plan_followup(flip(), asked=qs) == []
    sms = flip()
    sms["normalized"]["counterparty"]["contact_method"] = "phone"
    (ph,) = P.plan_followup(sms, asked=qs[:2])
    assert ph["comms"]["template_id"] == "seller_photo_request" and ph["capability"] == "comms.sms.send"
    (sv,) = P.plan_followup(service())
    assert sv["comms"]["template_id"] == "customer_photo_request"
    none = flip()
    none["normalized"]["counterparty"]["contact_method"] = "none"
    assert P.plan_followup(none) == [] and P.plan_offer(none, 900, "x", "y") == []


def test_offer_text_inputs_are_sanitized():
    (pa,) = P.plan_offer(flip(), 900, "Sat {{disclosure}} <b>", "https://evil.example soon")
    v = pa["comms"]["variables"]
    assert "{" not in v["pickup_window"] and "<" not in v["pickup_window"] and "http" not in v["offer_expires"]


# ---------------------------------------------------------------- on the spine
def _awaiting_item(rt, discover):
    item_id = discover("FIX-TRAILER-1")["FIX-TRAILER-1"]
    end = time.monotonic() + 30
    while q(rt.engine, "SELECT state FROM mbos.items WHERE item_id = :i", i=item_id)[0][0] != "AWAITING_APPROVAL":
        assert time.monotonic() < end
        time.sleep(0.1)
    return q(rt.engine, "SELECT body FROM mbos.items WHERE item_id = :i", i=item_id)[0][0]


def test_binding_offer_becomes_its_own_tier0_step_up_request_and_never_auto_sends(rt, discover):
    item = _awaiting_item(rt, discover)
    ask = item["normalized"]["price"]["amount"]
    (pa,) = P.plan_offer(item, ask - 100, "Saturday morning", "Sunday 6pm")
    with rt.engine.begin() as c:  # the spine's own insert path validates the contract and runs the PDP
        prov = tool_provenance(c, "tests.f08.offer")
        areq = spine._propose(c, item, pa, prov, components())
    assert areq["category"] == "offer" and areq["tier"] == 0 and areq["reversibility"] == "irreversible"
    assert areq["payload"]["comms"]["is_binding"] is True and spine.requires_step_up(areq)
    status = q(rt.engine, "SELECT status FROM mbos.action_requests WHERE action_request_id = :a",
               a=areq["action_request_id"])[0][0]
    assert status == "pending_approval"
    with pytest.raises(spine.DecisionRefused, match="step-up"):
        with rt.engine.begin() as c:
            spine.decide(c, areq["action_request_id"], "YES", areq["payload_hash"], components(), channel="web",
                         auth_context={"step_up": False})
    time.sleep(1.0)  # no workflow, gateway or effector touches a binding draft on its own
    assert q(rt.engine, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a",
             a=areq["action_request_id"])[0][0] == 0


def test_effector_blocks_binding_draft_smuggled_under_a_comms_capability(rt, discover):
    item = _awaiting_item(rt, discover)
    areq = q(rt.engine, "SELECT body FROM mbos.action_requests WHERE item_id = :i AND status = 'pending_approval'",
             i=item["item_id"])[0][0]
    (pa,) = P.plan_offer(item, item["normalized"]["price"]["amount"] - 50, "Sat", "Sun")
    eff = CommsDryRunEffector(clock=lambda: NOON_AR)
    smuggled = dict(copy.deepcopy(areq), capability="comms.email.send", idempotency_key="t-f08-smuggle",
                    payload={**areq["payload"], "comms": pa["comms"]})
    r = eff.execute(rt.engine, smuggled)
    assert r["status"] == "blocked" and any("binding draft under a non-offer capability" in x for x in r["comms"]["blocked_reasons"])
    proper = dict(smuggled, capability="offer.email.send", idempotency_key="t-f08-proper")
    r = eff.execute(rt.engine, proper)
    assert r["status"] == "simulated_send" and r["comms"]["binding"] is True and r["dry_run"] is True
