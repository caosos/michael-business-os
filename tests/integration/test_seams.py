"""Spine-side fixes from the 2026-10-07 lane review: blocking-key dedup, step-up, MODIFY by full payload."""

from dataclasses import asdict

import pytest
import sqlalchemy as sa

from mbos import spine
from mbos.interfaces import RawListing
from mbos.reference.fixture_adapter import FixtureNormalizer, FixtureSourceAdapter
from mbos.runtime import Components
from tests.helpers.common import FIXTURE, STEP_UP, scalar
from tests.helpers.seed import seed_flow


class NeverDuplicate:
    def is_duplicate(self, existing_item, candidate):
        return False


def _raw(listing):
    return next(r for r in FixtureSourceAdapter(FIXTURE).fetch() if r.source_listing_id == listing)


def test_equal_blocking_key_does_not_merge_without_deduper_consent(ledger_db):
    comps = Components(deduper=NeverDuplicate()).with_defaults()
    a, b = _raw("FIX-TRAILER-1"), _raw("FIX-TRAILER-1-DUP")
    n = FixtureNormalizer()
    with ledger_db.begin() as c:
        r1 = spine.ingest(c, asdict(a), asdict(n.normalize(a)), "fx", "0", comps)
        r2 = spine.ingest(c, asdict(b), asdict(n.normalize(b)), "fx", "0", comps)
        r3 = spine.ingest(c, asdict(a), asdict(n.normalize(a)), "fx", "0", comps)  # same identity again
    assert r1["created"] and r2["created"] and r1["item_id"] != r2["item_id"]
    assert r3 == {"item_id": r1["item_id"], "created": False, "merged": False, "dropped": False}
    assert scalar(ledger_db, "SELECT count(*) FROM mbos.items") == 2


def test_yes_on_irreversible_request_requires_step_up(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    with ledger_db.begin() as c:
        h = c.execute(sa.text("SELECT payload_hash FROM mbos.action_requests")).scalar_one()
        with pytest.raises(spine.DecisionRefused, match="step-up"):
            spine.decide(c, ids["action_request_id"], "YES", h, ids["components"])
    with ledger_db.begin() as c:
        out = spine.decide(c, ids["action_request_id"], "YES", h, ids["components"], auth_context=STEP_UP)
    assert out["approval"]["auth_context"]["step_up"] is True


def test_modify_accepts_full_edited_payload(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    with ledger_db.begin() as c:
        areq = c.execute(sa.text("SELECT body FROM mbos.action_requests")).scalar_one()
        edited = {**areq["payload"], "summary": "Offer $700 (DRY-RUN draft)"}
        out = spine.decide(c, ids["action_request_id"], "MODIFY", areq["payload_hash"], ids["components"], new_payload=edited)
    assert out["approval"]["modifications"]["diff"] == {"summary": "Offer $700 (DRY-RUN draft)"}
    with ledger_db.begin() as c, pytest.raises(spine.DecisionRefused, match="remove"):
        new = c.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a"),
                        {"a": out["new_action_request_id"]}).scalar_one()
        spine.decide(c, new["action_request_id"], "MODIFY", new["payload_hash"], ids["components"], new_payload={"summary": "x"})


def test_notify_event_wakes_matching_hold_and_never_executes(rt, run_discovery):
    from datetime import timedelta

    from mbos import workflows
    from mbos.clock import iso, utcnow
    from tests.helpers.common import pending_request, receipts_for, wait_state

    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    workflows.notify_event(item_id, "new_info", "seller added photos")  # awaiting → re-notified only
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": iso(utcnow() + timedelta(hours=6)), "wake_on": ["price_change"],
                                    "renotify_after": "PT6H"})
    wait_state(rt.engine, item_id, "HELD")
    workflows.notify_event(item_id, "auction_ending", "not in wake_on")  # ignored while held
    workflows.notify_event(item_id, "price_change", "ask dropped 950 -> 800")
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    intents = [r["intent"] for r in receipts_for(rt.engine, areq=areq["action_request_id"], type="APPROVAL_REQUESTED")]
    assert any("new_info" in i for i in intents) and any("price_change" in i for i in intents)
    assert not any("auction_ending" in i for i in intents)
    assert not receipts_for(rt.engine, areq=areq["action_request_id"], type="ACTION_EXECUTING")
    with pytest.raises(ValueError):
        workflows.notify_event(item_id, "buy_now")
    workflows.record_decision(areq["action_request_id"], "NO", areq["payload_hash"], reason="cleanup")
    wait_state(rt.engine, item_id, "ARCHIVED")
