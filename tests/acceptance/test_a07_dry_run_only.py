"""A7. In round one and the MVP, 100% of effector receipts have dry_run=true. Audit query: zero exceptions."""

import pytest
import sqlalchemy as sa

from mbos import audit, ledger
from mbos.config import Settings, configure, settings
from mbos.reference.governance import DryRunEffector, ReferenceGateway, TableKillSwitch
from tests.helpers.common import STEP_UP
from tests.helpers.seed import seed_flow

pytestmark = pytest.mark.acceptance


def test_audit_query_finds_zero_exceptions(ledger_db):
    seed_flow(ledger_db)
    with ledger_db.connect() as c:
        res = audit.dry_run_exceptions(c)
    assert res["ok"] and res["effector_receipts"] >= 1, res


def test_db_refuses_a_non_dry_run_effector_receipt(ledger_db):
    ids = seed_flow(ledger_db)
    with pytest.raises(sa.exc.IntegrityError, match="mvp_dry_run_only"):
        with ledger_db.begin() as c:
            prov = ledger.tool_provenance(c, "tests.a7")
            ledger.append_receipt(c, type="ACTION_EXECUTED", intent="live send", provenance_ids=[prov],
                                  item_id=ids["item_id"], action_request_id=ids["action_request_id"],
                                  approval_id=ids["approval_id"], capability="comms.email.send",
                                  payload_hash="sha256:" + "a" * 64, effect="send",
                                  effector_response={"provider": "postmark", "dry_run": False})


def test_db_refuses_a_non_dry_run_effector_call(ledger_db):
    ids = seed_flow(ledger_db)
    with pytest.raises(sa.exc.IntegrityError, match="effector_mvp_dry_run_only"):
        with ledger_db.begin() as c:
            c.execute(sa.text("INSERT INTO mbos.effector_calls (idempotency_key, action_request_id, capability, provider, "
                              "provider_msg_id, dry_run, request, response) VALUES ('live', :a, 'comms.email.send', "
                              "'postmark', 'x', false, '{}', '{}')"), {"a": ids["action_request_id"]})


def test_gateway_refuses_when_dry_run_mode_is_off(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    import dataclasses

    from mbos import spine
    with ledger_db.begin() as c:
        h = c.execute(sa.text("SELECT payload_hash FROM mbos.action_requests")).scalar_one()
        appr = spine.decide(c, ids["action_request_id"], "YES", h, ids["components"], auth_context=STEP_UP)["approval"]
    live = dataclasses.replace(settings(), dry_run=False)
    configure(live)

    class LiveLookingEffector(DryRunEffector):
        dry_run = False

    try:
        for eff in (DryRunEffector(), LiveLookingEffector()):
            res = ReferenceGateway(eff, TableKillSwitch()).execute(ledger_db, ids["action_request_id"], appr["approval_id"])
            assert not res.ok and res.checks["dry_run_mode"] is False
    finally:
        configure(dataclasses.replace(live, dry_run=True))
    with ledger_db.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM mbos.effector_calls")).scalar_one() == 0
