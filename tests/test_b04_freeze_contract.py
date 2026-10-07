"""B-04: source-health → L2 freeze request, agreed shape with lane E, tested against a shared fixture (real-store
round trips now on Postgres: test_b09_pg_panic.py). Discovery requests freezes; lane E holds them; discovery honours
every L1/L2/L3 freeze and fails closed when the PANIC state is unusable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from conftest import FIX, FLIP, SERVICE, StaticAdapter, World
from mbos_discovery import AGENT_ID
from mbos_discovery.adapter import SourceError
from mbos_discovery.adapters import EbayBrowseAdapter, GsaAuctionsAdapter
from mbos_discovery.health import UnavailablePanic, capability_for
from mbos_discovery.http import CallbackTransport, HttpResponse

ROOT = Path(__file__).resolve().parents[1] / "docs" / "integration" / "freeze-request"
SCHEMA = json.loads((ROOT / "freeze-request.schema.json").read_text())
EXAMPLES = {p.name: json.loads(p.read_text()) for p in sorted((ROOT / "examples").glob("*.json"))}
V = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
GSA = FLIP.__class__("flip-gsa", "flip")


def _valid(req):
    assert not [e.message for e in V.iter_errors(req)]
    assert req["capability"] == capability_for(req["source"])


def test_schema_and_examples_are_valid():
    Draft202012Validator.check_schema(SCHEMA)
    assert len(EXAMPLES) == 2
    for ex in EXAMPLES.values():
        _valid(ex)


def test_agent_id_is_branch_name():
    assert AGENT_ID == "agent-02-opportunity"


def _blocked_ebay(world, status):
    def handler(m, u, h, b):
        if m == "POST":
            return HttpResponse(200, b'{"access_token":"t","expires_in":7200}')
        return HttpResponse(status, b"<html>captcha</html>" if status == 200 else b"no")
    return EbayBrowseAdapter("id", "s", transport=CallbackTransport(handler), clock=world.clock)


def test_emitted_429_request_equals_shared_example(world):
    ad = _blocked_ebay(world, 429)
    world.run([(ad, FLIP)])
    req, = world.run([(ad, FLIP)]).freeze_requests
    _valid(req)
    assert req == EXAMPLES["freeze-request-429.json"] | {"reason": req["reason"]}
    assert req["reason"] == EXAMPLES["freeze-request-429.json"]["reason"]


def test_emitted_captcha_request_equals_shared_example(world):
    ad = GsaAuctionsAdapter("k", live=True, clock=world.clock,
                            transport=CallbackTransport(lambda *a: HttpResponse(200, b"<html>Complete the CAPTCHA</html>")))
    req, = world.run([(ad, GSA)]).freeze_requests
    _valid(req)
    assert req == EXAMPLES["freeze-request-captcha.json"]


# ---------------------------------------------------------------- honouring lane E's PANIC state
class FakeState:
    def __init__(self, reasons):
        self.reasons = reasons

    def blocks(self, agent_id, capability, category):
        return [r for r in self.reasons if r.endswith(capability) or r.endswith(agent_id) or r == "L3"]


class FakePanic:
    def __init__(self, reasons):
        self.state = FakeState(reasons)
        self.calls = []

    def read(self):
        return self.state


def test_l2_freeze_skips_only_that_source_with_zero_requests(world):
    ebay_calls = []
    ebay = EbayBrowseAdapter("id", "s", clock=world.clock, transport=CallbackTransport(
        lambda *a: ebay_calls.append(a) or HttpResponse(200, b"{}")))
    other = StaticAdapter("craigslist", [[{"id": "x", "title": "air compressor", "price": 50, "city": "Conway"}]],
                          world.clock)
    panic = FakePanic([f"PANIC_L2_CAPABILITY:{capability_for('ebay')}"])
    r = world.run([(ebay, FLIP), (other, FLIP)], enabled=frozenset({"craigslist"}), panic=panic)
    assert r.sources[0].status == "skipped" and "PANIC_L2_CAPABILITY" in r.sources[0].skipped_reason
    assert ebay_calls == [] and r.sources[1].status == "ok"


def test_unreadable_panic_state_fails_closed(world):
    ad = StaticAdapter("craigslist", [[]], world.clock)
    r = world.run([(ad, FLIP)], enabled=frozenset({"craigslist"}), panic=UnavailablePanic("governance missing"))
    assert r.sources[0].status == "skipped" and "PANIC_STATE_ERROR" in r.sources[0].skipped_reason
    assert ad.fetch_calls == 0


def test_spine_adapter_honours_panic(tmp_path):
    pytest.importorskip("mbos")
    from conftest import Clock
    from mbos_discovery.spine import discovery_components
    clock = Clock()
    adapters, _, _, side = discovery_components(
        [(EbayBrowseAdapter.from_fixture(FIX / "ebay", clock), FLIP)], raw_dir=tmp_path / "raw", clock=clock,
        panic=FakePanic([f"PANIC_L2_CAPABILITY:{capability_for('ebay')}"]))
    assert adapters["ebay:flip-test"].fetch() == []
    assert side.events[-1]["kind"] == "skipped" and side.events[-1]["reason"].startswith("PANIC:")


# ---------------------------------------------------------------- round trip with lane E's real store
# Moved to tests/test_b09_pg_panic.py: since E-02 (agent-05 1c554cb) PANIC lives in Postgres (lane D
# mbos.panic_state) and the file-based PanicStore these tests used (b632583) no longer exists. The Postgres
# versions cover the same cases: shared examples applied by lane E's gateway, human-only release, broader
# L2-prefix / L1 / L3 freezes, and fail-closed on an unreadable state.
