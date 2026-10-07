"""A8. The LLM spend cap blocks further calls once exceeded, regardless of agent behaviour.

Scope note: this proves the spine's per-agent ledger cap (`LedgerLLMBudget`). Enforcing the same
cap at the LiteLLM proxy (virtual keys) is Lane E work and is tracked as A8-LITELLM in RUNBOOK.md."""

import pytest

from mbos.interfaces import BudgetExceeded
from mbos.reference.governance import LedgerLLMBudget

pytestmark = pytest.mark.acceptance


def test_cap_blocks_once_exceeded(ledger_db):
    budget = LedgerLLMBudget(caps={"agent-02-discovery": 0.10, "*": 0.0})
    with ledger_db.begin() as c:
        budget.authorize(c, "agent-02-discovery", 0.06)
        budget.record(c, "agent-02-discovery", 0.06)
    with ledger_db.begin() as c:
        budget.authorize(c, "agent-02-discovery", 0.04)
        budget.record(c, "agent-02-discovery", 0.04)
    for est in (0.01, 0.0001):
        with pytest.raises(BudgetExceeded):
            with ledger_db.begin() as c:
                budget.authorize(c, "agent-02-discovery", est)


def test_default_cap_is_zero_in_the_mvp(ledger_db):
    budget = LedgerLLMBudget()  # settings default: {"*": 0.0}
    with pytest.raises(BudgetExceeded):
        with ledger_db.begin() as c:
            budget.authorize(c, "any-agent", 0.000001)


def test_agent_cannot_reset_its_own_spend(ledger_db):
    import sqlalchemy as sa
    budget = LedgerLLMBudget(caps={"a": 1.0})
    with ledger_db.begin() as c:
        budget.record(c, "a", 1.0)
    with pytest.raises(sa.exc.DBAPIError, match="insert-only"):
        with ledger_db.begin() as c:
            c.execute(sa.text("SET LOCAL ROLE agent_write"))
            c.execute(sa.text("DELETE FROM mbos.llm_spend WHERE agent_id = 'a'"))
