"""A8 (real spine): the LLM spend cap blocks further calls once reached, regardless of agent behaviour.
Implementation under test: `mbos.reference.governance.LedgerLLMBudget` (Postgres ledger). LiteLLM is lane E's (F-7)."""
import threading

import pytest


def _budget(caps):
    from mbos.reference.governance import LedgerLLMBudget

    return LedgerLLMBudget(caps)


def _call(led, b, agent, usd):
    with led.engine.begin() as c:
        b.authorize(c, agent, usd)
        b.record(c, agent, usd)


def test_blocks_once_cap_reached_and_retries_stay_blocked(qa, led):
    from mbos.interfaces import BudgetExceeded

    b = _budget({"agent-x": 0.05})
    for _ in range(5):
        _call(led, b, "agent-x", 0.01)
    for usd in (0.01, 0.001, 0.0001):
        with pytest.raises(BudgetExceeded):
            _call(led, b, "agent-x", usd)
    with led.engine.connect() as c:
        assert b.spent_today(c, "agent-x") == pytest.approx(0.05)


def test_negative_spend_cannot_buy_headroom(qa, led):
    b = _budget({"agent-x": 0.01})
    import sqlalchemy as sa

    with pytest.raises(sa.exc.DBAPIError):
        _call(led, b, "agent-x", -1.0)


def test_parallel_calls_never_overshoot(qa, led):
    from mbos.interfaces import BudgetExceeded

    b = _budget({"agent-x": 0.10})
    ok, blocked = [], []
    barrier = threading.Barrier(30)

    def go():
        barrier.wait()
        try:
            _call(led, b, "agent-x", 0.01)
            ok.append(1)
        except BudgetExceeded:
            blocked.append(1)

    ts = [threading.Thread(target=go) for _ in range(30)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    with led.engine.connect() as c:
        spent = b.spent_today(c, "agent-x")
    assert len(ok) == 10 and len(blocked) == 20 and spent == pytest.approx(0.10)


def test_unknown_agent_defaults_to_zero(qa, led):
    from mbos.interfaces import BudgetExceeded

    with pytest.raises(BudgetExceeded):
        _call(led, _budget({"*": 0.0, "agent-a": 1.0}), "agent-rogue", 0.0001)
