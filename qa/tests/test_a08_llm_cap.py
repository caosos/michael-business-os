"""A8 — the LLM cap blocks further calls once exceeded, regardless of agent behavior.
Mock limitation: enforced by the in-process LLMBudget stand-in, not a LiteLLM proxy. Re-run against
Agent 05's LiteLLM virtual keys before MVP sign-off (finding F-8)."""
import threading

import pytest

from mbos_qa.mocks.governance import LLMBudget, LLMBudgetExceeded


def provider(completion_tokens):
    calls = []

    def fn(max_tokens):
        calls.append(max_tokens)
        return {"prompt_tokens": 100, "completion_tokens": completion_tokens}
    fn.calls = calls
    return fn


def test_blocks_once_cap_is_reached():
    b = LLMBudget({"agent-x": 0.05}, price_per_1k_tokens=0.01)  # 5,000 tokens
    p = provider(900)
    made = 0
    with pytest.raises(LLMBudgetExceeded):
        for _ in range(100):
            b.call("agent-x", prompt_tokens=100, max_tokens=900, provider_fn=p)
            made += 1
    assert made == 5 and len(p.calls) == 5
    assert b.spent["agent-x"] <= 0.05 + 1e-9
    for _ in range(10):  # retries, smaller requests, zero-token requests: all blocked
        for mt in (900, 1, 0):
            with pytest.raises(LLMBudgetExceeded):
                b.call("agent-x", prompt_tokens=0, max_tokens=mt, provider_fn=p)
    assert len(p.calls) == 5


def test_agent_cannot_under_report_cost():
    b = LLMBudget({"agent-x": 0.03}, price_per_1k_tokens=0.01)
    for bad in (-10_000, None, "lots"):
        b.call("agent-x", prompt_tokens=100, max_tokens=900, provider_fn=provider(bad))
    assert b.spent["agent-x"] == pytest.approx(0.01 * 3)  # each malformed count charged at worst case
    with pytest.raises(LLMBudgetExceeded):
        b.call("agent-x", prompt_tokens=100, max_tokens=900, provider_fn=provider(1))


def test_parallel_calls_never_overshoot():
    b = LLMBudget({"agent-x": 0.10}, price_per_1k_tokens=0.01)
    p = provider(900)
    ok, blocked = [], []
    barrier = threading.Barrier(50)

    def go():
        barrier.wait()
        try:
            b.call("agent-x", prompt_tokens=100, max_tokens=900, provider_fn=p)
            ok.append(1)
        except LLMBudgetExceeded:
            blocked.append(1)

    ts = [threading.Thread(target=go) for _ in range(50)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(ok) == 10 and len(blocked) == 40
    assert b.spent["agent-x"] <= 0.10 + 1e-9


def test_unknown_agent_has_no_budget_and_caps_are_per_agent():
    b = LLMBudget({"agent-a": 0.01}, price_per_1k_tokens=0.01)
    with pytest.raises(LLMBudgetExceeded):
        b.call("agent-rogue", prompt_tokens=1, max_tokens=1, provider_fn=provider(1))
    b.call("agent-a", prompt_tokens=100, max_tokens=900, provider_fn=provider(900))
    with pytest.raises(LLMBudgetExceeded):
        b.call("agent-a", prompt_tokens=1, max_tokens=1, provider_fn=provider(1))


def test_harness_wires_a_capped_llm_budget(h):
    assert h.llm.caps and all(v > 0 for v in h.llm.caps.values())
