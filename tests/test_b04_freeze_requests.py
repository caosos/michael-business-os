"""B-04 lane-E half: Agent 02's shared freeze-request fixture applied through lane E's PANIC.
Fixture: tests/data/b04/*.json = agent-02-opportunity @ 029356c docs/integration/freeze-request/examples/ (pinned)."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from mbos_governance.freeze_requests import apply_freeze_request, apply_side_channel, problems
from mbos_governance.gateway import GatewayRefused

DATA = Path(__file__).parent / "data" / "b04"
PINNED = {
    "freeze-request-429.json": "26a826b0de111fc41159c13b97270570b9f2b1eacd1fb521fd1ec1ec9e7cc3d5",
    "freeze-request-captcha.json": "e56b2d343bbf94726cc846cfa436b4da235f876b343f2720c97b28443e1512af",
}
SCHEMA_SHA = "2995d2c1b4709a264dce94102bbdb6a00c7353162a5e5316c29b6146f7a5e92f"
EXAMPLES = {n: json.loads((DATA / n).read_text()) for n in PINNED}


def test_fixture_and_schema_are_pinned():
    for n, h in PINNED.items():
        assert hashlib.sha256((DATA / n).read_bytes()).hexdigest() == h
    schema = Path(__file__).parents[1] / "src/mbos_governance/schemas/freeze-request.schema.json"
    assert hashlib.sha256(schema.read_bytes()).hexdigest() == SCHEMA_SHA


@pytest.mark.parametrize("name", sorted(PINNED))
def test_example_applies_and_blocks_exactly_that_source(env, name):
    req = EXAMPLES[name]
    out = apply_freeze_request(env.gw, req)
    assert out.applied and out.capability == req["capability"]
    st = env.panic.read()
    # lane B's exact honour check (README §3)
    assert st.blocks("agent-02-opportunity", req["capability"], "discovery") == [f"PANIC_L2_CAPABILITY:{req['capability']}"]
    other = "discovery.source.craigslist.read"
    assert st.blocks("agent-02-opportunity", other, "discovery") == []
    r = [x for x in env.store.receipts() if x["type"] == "KILL_SWITCH_CHANGED"][-1]
    assert r["actor"]["id"] == "agent-02-opportunity" and req["source"] in r["intent"]


def test_release_is_human_only(env):
    req = EXAMPLES["freeze-request-429.json"]
    apply_freeze_request(env.gw, req)
    with pytest.raises(GatewayRefused):
        env.gw.release_panic("L2", req["capability"], "agent-02-opportunity", "self-release")
    assert env.panic.read().blocks("agent-02-opportunity", req["capability"], "discovery")
    env.gw.release_panic("L2", req["capability"], "michael", "source healthy again")
    assert env.panic.read().blocks("agent-02-opportunity", req["capability"], "discovery") == []


def test_reapply_is_idempotent(env):
    req = EXAMPLES["freeze-request-captcha.json"]
    assert apply_freeze_request(env.gw, req).applied
    rev = env.panic.read().revision
    again = apply_freeze_request(env.gw, req)
    assert not again.applied and again.reasons == ["ALREADY_FROZEN"] and env.panic.read().revision == rev


@pytest.mark.parametrize("mutate,code", [
    (lambda r: r.__setitem__("capability", "money.payment.send"), "SCHEMA"),           # cannot touch other lanes
    (lambda r: r.__setitem__("capability", "discovery.source.*"), "SCHEMA"),           # no prefix freezes via request
    (lambda r: r.__setitem__("requested_by", "agent-07-marketing"), "SCHEMA"),
    (lambda r: r.__setitem__("level", "L3"), "SCHEMA"),
    (lambda r: r.__setitem__("source", "craigslist"), "CAPABILITY_SOURCE_MISMATCH"),
    (lambda r: r.__setitem__("extra", 1), "SCHEMA"),
])
def test_invalid_requests_are_refused_and_not_applied(env, mutate, code):
    req = copy.deepcopy(EXAMPLES["freeze-request-429.json"])
    mutate(req)
    rev = env.panic.read().revision
    out = apply_freeze_request(env.gw, req)
    assert not out.applied and out.reasons[0].startswith(code)
    assert env.panic.read().revision == rev


def test_side_channel_jsonl(env, tmp_path):
    p = tmp_path / "side.jsonl"
    lines = [{"kind": "source_health", "source": "ebay"},
             {"kind": "freeze_request", "freeze_request": EXAMPLES["freeze-request-429.json"]},
             {"kind": "freeze_request", "freeze_request": {"schema": "bogus"}}]
    p.write_text("\n".join(json.dumps(x, sort_keys=True) for x in lines) + "\n{not json\n")
    outs = apply_side_channel(env.gw, p)
    assert [o.applied for o in outs] == [True, False, False]
    assert outs[2].reasons[0].startswith("LINE_4_UNPARSABLE")
    assert problems(None) == ["NOT_AN_OBJECT"]
