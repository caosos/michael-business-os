"""Source failures fail safely (F3), forbidden sources are never touched (F4), and the
lane is structurally incapable of side effects."""

import json

import pytest

from conftest import FIX, FLIP, SERVICE, StaticAdapter, World
from mbos_discovery.adapter import SourceAdapter, SourceError
from mbos_discovery.adapters import EbayBrowseAdapter, ServiceIntakeAdapter
from mbos_discovery.health import DEGRADED, FROZEN, HEALTHY
from mbos_discovery.http import CallbackTransport, HttpResponse, ReadOnlyTransport, SideEffectRefused
from mbos_discovery.policy import REGISTRY, Disposition, SourceRefused, check_allowed

GOOD = [{"id": "g1", "title": "Air compressor 60 gallon", "price": 300, "city": "Conway", "state": "AR"}]


def test_crashing_adapter_does_not_stop_the_run(world):
    boom = StaticAdapter("craigslist", [RuntimeError("adapter bug")], world.clock)
    report = world.run([(boom, FLIP)] + world.jobs(), enabled=frozenset({"craigslist"}))
    assert report.sources[0].status == "error" and report.sources[0].error["kind"] == "crash"
    assert all(s.status == "ok" for s in report.sources[1:])
    assert world.store.items                                # other sources still produced Items
    assert world.health.get("craigslist").status == DEGRADED


def test_failed_fetch_leaves_existing_items_untouched(world):
    world.run()
    before = world.dump()
    world.clock.advance(hours=1)
    broken = EbayBrowseAdapter("id", "secret", transport=CallbackTransport(
        lambda m, u, h, b: HttpResponse(503, b"upstream down")), clock=world.clock)
    report = world.run([(broken, FLIP)])
    assert report.sources[0].error["kind"] == "http"
    assert world.dump() == before


@pytest.mark.parametrize("status,kind", [(429, "rate_limited"), (403, "blocked")])
def test_repeated_block_freezes_source_and_stops_requests(world, status, kind):
    calls = []

    def handler(m, u, h, b):
        calls.append(m)
        return HttpResponse(200, b'{"access_token":"t","expires_in":7200}') if m == "POST" else HttpResponse(status, b"no")

    ad = EbayBrowseAdapter("id", "secret", transport=CallbackTransport(handler), clock=world.clock)
    r1 = world.run([(ad, FLIP)])
    assert r1.sources[0].error["kind"] == kind and not r1.freeze_requests
    r2 = world.run([(ad, FLIP)])
    assert world.health.get("ebay").status == FROZEN
    assert r2.freeze_requests == [{**r2.freeze_requests[0], "level": "L2",
                                   "capability": "discovery.source.ebay.read"}]
    n = len(calls)
    r3 = world.run([(ad, FLIP)])
    assert r3.sources[0].status == "skipped" and "FROZEN" in r3.sources[0].skipped_reason
    assert len(calls) == n                                  # no request after the freeze


def test_captcha_freezes_immediately(world):
    def handler(m, u, h, b):
        if m == "POST":
            return HttpResponse(200, b'{"access_token":"t","expires_in":7200}')
        return HttpResponse(200, b"<html>Please complete the CAPTCHA to continue</html>")

    ad = EbayBrowseAdapter("id", "secret", transport=CallbackTransport(handler), clock=world.clock)
    report = world.run([(ad, FLIP)])
    assert report.sources[0].error["kind"] == "captcha"
    assert world.health.get("ebay").status == FROZEN and report.freeze_requests


def test_freeze_cleared_only_by_human_then_recovers(world):
    ad = StaticAdapter("craigslist", [SourceError("rate_limited", "429", 429)] * 2 + [GOOD], world.clock)
    for _ in range(2):
        world.run([(ad, FLIP)], enabled=frozenset({"craigslist"}))
    assert world.health.get("craigslist").status == FROZEN
    world.health.clear_freeze("craigslist", "michael", world.clock())
    assert world.health.get("craigslist").status == DEGRADED
    world.run([(ad, FLIP)], enabled=frozenset({"craigslist"}))
    assert world.health.get("craigslist").status == HEALTHY


def test_non_block_errors_do_not_freeze(world):
    ad = StaticAdapter("craigslist", [SourceError("network", "timeout")], world.clock)
    for _ in range(5):
        world.run([(ad, FLIP)], enabled=frozenset({"craigslist"}))
    h = world.health.get("craigslist")
    assert h.status == DEGRADED and h.consecutive_failures == 5


def test_bad_record_quarantined_with_raw_retained(world):
    ad = StaticAdapter("craigslist", [[{"id": "x", "title": "t", "price": 1, "boom": 1}] + GOOD], world.clock)
    report = world.run([(ad, FLIP)], enabled=frozenset({"craigslist"}))
    assert report.sources[0].quarantined == 1 and report.sources[0].created == 1
    q = report.quarantine[0]
    assert q["raw_ref"] and world.raw.exists(q["raw_ref"])


def test_malformed_intake_file_is_quarantined(world):
    report = world.run()
    ref = next(s for s in report.sources if s.source == "referral")
    assert ref.quarantined == 1
    assert any(q["source"] == "referral" and world.raw.exists(q["raw_ref"]) for q in report.quarantine)


def test_missing_credentials_fail_safe_without_network():
    calls = []
    ad = EbayBrowseAdapter.from_env({}, transport=CallbackTransport(lambda *a: calls.append(a)))
    w = World()
    report = w.run([(ad, FLIP)])
    assert report.sources[0].error["kind"] == "config" and calls == []


def test_missing_inbox_fails_safe(tmp_path):
    w = World()
    report = w.run([(ServiceIntakeAdapter("website_lead", tmp_path / "nope", w.clock), SERVICE)])
    assert report.sources[0].error["kind"] == "config"


# ---- F4: do-not-automate ----------------------------------------------------------------
@pytest.mark.parametrize("source", sorted(s for s, p in REGISTRY.items() if p.disposition is Disposition.FORBIDDEN))
def test_forbidden_sources_never_fetched_even_if_enabled(world, source):
    ad = StaticAdapter(source, [GOOD], world.clock)
    report = world.run([(ad, FLIP)], enabled=frozenset({source}))
    assert report.sources[0].status == "skipped" and ad.fetch_calls == 0
    with pytest.raises(SourceRefused):
        check_allowed(source, frozenset({source}))


@pytest.mark.parametrize("source", ["craigslist", "govdeals", "hibid", "some_unregistered_site"])
def test_gray_zone_and_unknown_sources_need_explicit_enablement(world, source):
    ad = StaticAdapter(source, [GOOD], world.clock)
    report = world.run([(ad, FLIP)])
    assert report.sources[0].status == "skipped" and ad.fetch_calls == 0


def test_facebook_and_nextdoor_are_forbidden():
    for s in ("facebook_marketplace", "facebook_groups", "nextdoor"):
        assert REGISTRY[s].disposition is Disposition.FORBIDDEN


# ---- no side effects ----------------------------------------------------------------------
def test_read_only_transport_refuses_writes():
    inner = CallbackTransport(lambda *a: HttpResponse(200, b"{}"))
    t = ReadOnlyTransport(inner, frozenset({"api.ebay.com"}),
                          frozenset({"https://api.ebay.com/identity/v1/oauth2/token"}))
    for method, url in [("POST", "https://api.ebay.com/buy/offer/v1_beta/bidding/x/place_proxy_bid"),
                        ("POST", "https://api.ebay.com/buy/order/v2/checkout_session/initiate"),
                        ("PUT", "https://api.ebay.com/anything"), ("DELETE", "https://api.ebay.com/anything"),
                        ("GET", "https://evil.example.com/"), ("GET", "http://api.ebay.com/plain-http")]:
        with pytest.raises(SideEffectRefused):
            t.request(method, url)
    assert inner.calls == []                                # nothing left the box


def test_fixture_run_makes_only_token_post_and_search_gets():
    w = World()
    ad = EbayBrowseAdapter.from_fixture(FIX / "ebay", w.clock)
    w.run([(ad, FLIP)])
    methods = {(m, u.split("?")[0]) for m, u, _ in ad.http.log}
    assert methods == {("POST", "https://api.ebay.com/identity/v1/oauth2/token"),
                       ("GET", "https://api.ebay.com/buy/browse/v1/item_summary/search")}


def test_adapter_interface_has_no_effectors():
    public = {n for n in dir(SourceAdapter) if not n.startswith("_")}
    assert public == {"fetch", "normalize", "tool_name"}


def test_intake_never_modifies_inbox(intake_copy):
    before = {p: p.read_bytes() for p in intake_copy.rglob("*") if p.is_file()}
    w = World(intake_copy)
    w.run()
    w.run()
    after = {p: p.read_bytes() for p in intake_copy.rglob("*") if p.is_file()}
    assert before == after
