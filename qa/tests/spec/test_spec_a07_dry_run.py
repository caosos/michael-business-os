"""A7 (real spine): 100% of effector receipts and effector calls are dry_run=true. Zero exceptions, non-vacuous."""
import pytest
import sqlalchemy as sa


def test_zero_exceptions_by_independent_query_and_by_spine_audit(qa, led):
    from mbos import audit

    for _ in range(2):
        led.seed()
    eff = [r for r in qa.receipts(led.engine) if r["type"] in ("ACTION_EXECUTED", "ACTION_FAILED")]
    assert len(eff) >= 2, "audit must not pass vacuously"
    assert all((r.get("effector_response") or {}).get("dry_run") is True for r in eff)
    assert all(row["dry_run"] is True for row in qa.effector_rows(led.engine))
    with led.engine.connect() as c:
        res = audit.dry_run_exceptions(c)
    assert res["ok"] and res["effector_receipts"] == len(eff), res


def test_database_refuses_a_live_effector_call(qa, led):
    out = led.seed(act=False)
    with pytest.raises(sa.exc.DBAPIError, match="effector_mvp_dry_run_only|check constraint"):
        led.superuser_sql(
            "INSERT INTO mbos.effector_calls (idempotency_key, action_request_id, capability, provider, provider_msg_id,"
            " dry_run, request, response) VALUES ('qa-live', :a, 'comms.email.send', 'live', 'x', false, '{}', '{}')",
            a=out["action_request_id"])


def test_spine_refuses_to_run_with_a_non_dry_run_effector(qa, led):
    out = led.seed(act=False)
    from mbos import spine

    class Live:
        name, dry_run = "live", False

        def execute(self, engine, areq):  # pragma: no cover - must never be reached
            raise AssertionError("live effector invoked")

    from mbos.reference.governance import ReferenceGateway

    led.comps.gateway = ReferenceGateway(Live(), led.comps.kill_switch)
    with led.engine.begin() as c:
        spine.begin_act(c, out["item_id"], out["action_request_id"], out["approval"])
    g = led.gateway(out["action_request_id"], out["approval"]["approval_id"])
    assert not g["ok"] and g["checks"]["dry_run_mode"] is False
