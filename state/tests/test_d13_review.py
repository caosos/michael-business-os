"""D-13 regressions found while reviewing Agent 01's lane-D backend (spine_d @ 8c3e4fd)."""

import psycopg
import pytest

from mbos_state.ids import new_id
from conftest import MICHAEL, key, make_areq, make_item, payload_hash, to_pending


def test_modify_with_provenance_written_before_its_approval(db):
    """spine_d.decide(MODIFY) order: provenance(approval_id=new) -> successor -> MODIFY approval, one transaction."""
    s = db.store("dbos")                      # the spine's real login (agent_write + approver + gateway)
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid)
    to_pending(s, areq, pid)
    appr_id = new_id("appr")
    with s.transaction():
        prov_m = s.record_provenance(actor_type="human", human_actor="michael", basis="FACT", approval_id=appr_id)
        succ = make_areq(s, item_id, prov_m, derived_from=areq, payload={"body": "offer $400"})
        s.record_approval({"approval_id": appr_id, "action_request_id": areq, "decision": "MODIFY", "decider": "michael",
                           "channel": "cli", "payload_hash_seen": payload_hash(s, areq), "scope": "once",
                           "modifications": {"new_action_request_id": succ, "new_payload_hash": payload_hash(s, succ)}},
                          MICHAEL, "MODIFY", key())
    assert s.verify_chain().ok


def test_provenance_cannot_commit_citing_a_missing_approval(db):
    s = db.store()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with s.transaction():
            s.record_provenance(actor_type="human", human_actor="michael", basis="FACT", approval_id=new_id("appr"))
