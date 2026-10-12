"""B-43: Facebook Marketplace via Bright Data: fixtures only; seller fields dropped; compliance label; token hygiene; cap."""

from __future__ import annotations

import json

import pytest

from conftest import FIX, T0
from mbos_discovery import contract
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters.brightdata_fb_marketplace import (HARD_CAP, SOURCE_COMPLIANCE,
                                                               BrightDataFbMarketplaceAdapter, read_token)
from mbos_discovery.http import CallbackTransport, HttpResponse, SideEffectRefused
from mbos_discovery.policy import Disposition, policy_for

P = SearchProfile("flip-fb", "flip", ("tools",), radius_miles=50)
TOKEN = "tok" + "-synthetic-" + "0123456789abcdef"


def test_policy_row_and_registry():
    p = policy_for("brightdata_fb")
    assert p.disposition is Disposition.ALLOWED and p.tier == 4 and "UNKNOWN (no Meta permission" in p.note
    from test_location import REG
    fb = next(s for s in REG if s["source_id"] == "fb_marketplace")
    assert fb["access_mode"] == "api" and fb["status"] == "fixture"


def test_fixture_run_normalizes_and_drops_seller(world):
    report = world.run([(BrightDataFbMarketplaceAdapter.from_fixture(FIX / "brightdata_fb", world.clock), P)])
    s = report.sources[0]
    assert (s.fetched, s.created, s.quarantined) == (3, 3, 0)
    by = {i["sources"][0]["source_listing_id"]: i for i in world.store.items.values()}
    drill = by["900000000000001"]["normalized"]
    assert drill["title"] == "DeWalt cordless drill set"
    assert drill["price"] == {"currency": "USD", "amount": 65.0, "type": "fixed"}
    assert drill["condition"] == "used" and drill["location"] == {"city": "Conway", "state": "AR"}
    assert "needs_review" in drill["flags"]
    trailer = by["900000000000002"]["normalized"]
    assert trailer["price"]["amount"] == 450.0 and trailer["location"]["lat"] == 35.0809
    assert trailer["location"]["geo_tier"] == 0
    free = by["900000000000003"]["normalized"]           # product_id from URL; null images tolerated
    assert free["price"]["type"] == "free" and "free" in free["flags"]
    for i in world.store.items.values():
        contract.check_item(i)
        assert i["sources"][0]["ingestion_method"] == "api" and i["sources"][0]["tos_risk"] == "high"
    blob = json.dumps(list(world.store.items.values()))
    assert "SELLERNAME" not in blob and "PROFILEID" not in blob


def test_seller_fields_dropped_at_ingest_and_label_on_every_record():
    res = BrightDataFbMarketplaceAdapter.from_fixture(FIX / "brightdata_fb", lambda: T0).fetch(P)
    assert len(res.records) == 3 and res.requests_made == 2
    for r in res.records:
        raw = r.raw_bytes.decode()
        assert "SELLERNAME" not in raw and "PROFILEID" not in raw and "seller" not in raw.lower().replace("source_compliance", "")
        assert r.payload["source_compliance"] == SOURCE_COMPLIANCE
        n = BrightDataFbMarketplaceAdapter.from_fixture(FIX / "brightdata_fb").normalize(r.payload, T0)
        assert n.match_hints["source_compliance"] == SOURCE_COMPLIANCE
    n = BrightDataFbMarketplaceAdapter.from_fixture(FIX / "brightdata_fb").normalize(res.records[0].payload, T0)
    assert n.match_hints["listing_date"] == "2026-10-10T14:03:00.000Z"
    assert n.match_hints["image_urls"] == ["https://images.example.invalid/a.jpg"]      # https only


def _calls_adapter(rows, status=200, **kw):
    seen = []

    def h(method, url, headers, body):
        seen.append((method, url, headers, body))
        return HttpResponse(status, json.dumps(rows).encode())

    return BrightDataFbMarketplaceAdapter(TOKEN, live=True, transport=CallbackTransport(h), **kw), seen


def test_request_shape_bearer_header_and_token_never_in_url_or_log():
    a, seen = _calls_adapter([{"url": "https://www.facebook.com/marketplace/item/1/", "title": "x", "product_id": "1"}])
    res = a.fetch(P)
    assert res.ok and len(res.records) == 1
    method, url, headers, body = seen[0]
    assert method == "POST" and "discover_by=keyword" in url and "limit_per_input=20" in url
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(body) == {"input": [{"keyword": "tools", "city": "Conway, AR", "radius": 50}]}
    assert TOKEN not in url and TOKEN not in repr(a) and TOKEN not in str(a.http.log)
    assert all(TOKEN not in r.request_uri and TOKEN.encode() not in r.raw_bytes for r in res.records)


@pytest.mark.parametrize("status,kind", [(401, "auth"), (429, "rate_limited"), (500, "http")])
def test_errors_never_carry_the_token(status, kind):
    def h(method, url, headers, body):
        return HttpResponse(status, f"denied for Bearer {TOKEN}".encode())

    res = BrightDataFbMarketplaceAdapter(TOKEN, live=True, transport=CallbackTransport(h)).fetch(P)
    assert res.error and res.error.kind == kind and TOKEN not in res.error.message


def test_transport_exception_text_is_scrubbed():
    from mbos_discovery.http import TransportError

    def h(*a):
        raise TransportError(f"connect failed using {TOKEN}")

    res = BrightDataFbMarketplaceAdapter(TOKEN, live=True, transport=CallbackTransport(h)).fetch(P)
    assert res.error.kind == "network" and TOKEN not in res.error.message


def test_hard_cap_applies_to_requests_and_output():
    rows = [{"url": f"https://www.facebook.com/marketplace/item/{i}/", "title": f"t{i}", "product_id": str(i)}
            for i in range(50)]
    a, seen = _calls_adapter(rows)
    res = a.fetch(SearchProfile("flip-fb", "flip", ("tools",), limit=500))
    assert HARD_CAP == 20 and len(res.records) == 20
    assert "limit_per_input=20" in seen[0][1]


def test_off_by_default_missing_token_and_no_other_hosts(tmp_path):
    a, seen = _calls_adapter([])
    a.live = False
    assert a.fetch(P).error.kind == "config" and not seen
    b = BrightDataFbMarketplaceAdapter(None, live=True, token_file=tmp_path / "none",
                                       transport=CallbackTransport(lambda *x: HttpResponse(200, b"[]")))
    assert b.fetch(P).error.kind == "config"
    with pytest.raises(SideEffectRefused):
        b.http.request("POST", "https://example.com/x", {}, b"{}")
    with pytest.raises(SideEffectRefused):
        b.http.request("DELETE", "https://api.brightdata.com/datasets/v3/scrape", {}, None)


def test_read_token_strips_whitespace(tmp_path):
    f = tmp_path / "t"
    f.write_text(f"  {TOKEN}\n")
    assert read_token(f) == TOKEN and read_token(tmp_path / "missing") is None
