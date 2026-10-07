"""A10. Every stored Item, ActionRequest, Approval, Receipt, Provenance and Outcome validates against
contracts/ (contract conformance). Runs last over the shared runtime DB (all workflow tests' data) and
over a seeded ledger DB that also holds an Outcome."""

import pytest

from mbos import audit
from tests.helpers.seed import seed_flow

pytestmark = pytest.mark.acceptance


def test_seeded_ledger_conforms(ledger_db):
    seed_flow(ledger_db)
    with ledger_db.connect() as c:
        res = audit.conformance(c)
    assert res["ok"], res["failures"][:10]
    assert all(res["counts"][k] > 0 for k in ("item", "action-request", "approval", "provenance", "outcome", "receipt"))


def test_zz_whole_runtime_database_conforms(rt, run_discovery):
    run_discovery("FIX-TRAILER-1", "FIX-TRAILER-1-DUP", "FIX-LEAD-DRYWALL-1", "FIX-LEAD-SMARTHOME-1", "FIX-MOWER-1")
    with rt.engine.connect() as c:
        res = audit.full_audit(c)
    assert res["chain"]["ok"], res["chain"]
    assert res["provenance"]["ok"], res["provenance"]
    assert res["dry_run"]["ok"], res["dry_run"]
    assert res["conformance"]["ok"], res["conformance"]["failures"][:10]
