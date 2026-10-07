"""B-03: credential-free official sources — GSA Auctions and Trash Nothing — fixture-first, read-only,
no live call without explicit enablement, keys never in provenance."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from conftest import FIX, FLIP, World
from mbos_discovery import contract
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import EbayBrowseAdapter, GsaAuctionsAdapter, TrashNothingAdapter
from mbos_discovery.health import FROZEN
from mbos_discovery.http import CallbackTransport, HttpResponse
from mbos_discovery.policy import Disposition, policy_for

GSA = SearchProfile("flip-gsa", "flip")
TN = SearchProfile("flip-free", "flip", radius_miles=100, limit=3)


def _by_listing(world):
    return {s["source_listing_id"]: i for i in world.store.items.values() for s in i["sources"]}


def test_both_sources_are_tier1_allowed():
    for s in ("gsa_auctions", "trashnothing"):
        assert policy_for(s).disposition is Disposition.ALLOWED and policy_for(s).tier == 1


# ---------------------------------------------------------------- GSA Auctions
def test_gsa_fixture_run(world):
    report = world.run([(GsaAuctionsAdapter.from_fixture(FIX / "gsa", world.clock), GSA)])
    s = report.sources[0]
    assert (s.fetched, s.created, s.quarantined) == (5, 4, 1)      # CA filtered; 1 AR lot lacks ItemName
    items = _by_listing(world)
    assert "93QSCI26301-1" not in items                               # outside the state filter
    trailer = items["71QSCI26101-1"]
    n = trailer["normalized"]
    assert (trailer["category"], trailer["opportunity_kind"]) == ("trailer", "auction_lot")
    assert n["price"] == {"currency": "USD", "type": "starting_bid", "buyer_premium_pct": 0}
    assert n["bid_count"] == 0 and "zero_bid" in n["flags"]
    assert n["ends_at"] == "2026-10-14T23:59:59Z"
    assert n["location"] == {"city": "Little Rock", "state": "AR", "zip": "72201"}
    assert n["description"].startswith("Steel deck")                  # LotInfo ordered by LotSequence
    assert n["counterparty"] == {"role": "agency", "contact_method": "gov_poc", "name": "DEPARTMENT OF DEFENSE"}
    gen = items["71QSCI26102-3"]["normalized"]
    assert gen["price"]["type"] == "auction_current" and gen["price"]["amount"] == 450
    assert "ending_soon" in gen["flags"]
    assert items["72QSCI26201-2"]["category"] == "commercial_equipment"
    blob = json.dumps(list(world.store.items.values()))
    assert "officer@example.invalid" not in blob and "5015550199" not in blob   # PoC stays in raw only
    for i in world.store.items.values():
        contract.check_item(i)


def test_gsa_requires_explicit_live_enablement_and_key():
    calls = []
    t = CallbackTransport(lambda *a: calls.append(a) or HttpResponse(200, b'{"results":[]}'))
    assert GsaAuctionsAdapter("k", live=False, transport=t).fetch(GSA).error.kind == "config"
    assert GsaAuctionsAdapter(None, live=True, transport=t).fetch(GSA).error.kind == "config"
    assert calls == []


def test_gsa_key_in_header_never_in_url():
    seen = []

    def handler(m, u, h, b):
        seen.append((m, u, h))
        return HttpResponse(200, b'{"results":[]}')

    res = GsaAuctionsAdapter("SECRET-KEY", live=True, transport=CallbackTransport(handler)).fetch(GSA)
    assert res.ok
    (m, u, h), = seen
    assert m == "GET" and u == "https://api.gsa.gov/assets/gsaauctions/v2/auctions?format=JSON"
    assert h["X-API-KEY"] == "SECRET-KEY" and "SECRET" not in u


def test_gsa_rate_limit_freezes(world):
    ad = GsaAuctionsAdapter("k", live=True, transport=CallbackTransport(lambda *a: HttpResponse(429, b"slow down")),
                            clock=world.clock)
    world.run([(ad, GSA)])
    r = world.run([(ad, GSA)])
    assert world.health.get("gsa_auctions").status == FROZEN and r.freeze_requests


def test_gsa_and_ebay_same_welder_merge_cross_source(world):
    world.run([(EbayBrowseAdapter.from_fixture(FIX / "ebay", world.clock), FLIP),
               (GsaAuctionsAdapter.from_fixture(FIX / "gsa", world.clock), GSA)])
    welders = [i for i in world.store.items.values() if i["category"] == "welder"]
    assert len(welders) == 1
    assert {s["source"] for s in welders[0]["sources"]} == {"ebay", "gsa_auctions"}
    assert all(s["raw_ref"] for s in welders[0]["sources"])


# ---------------------------------------------------------------- Trash Nothing
def test_trashnothing_fixture_run(world):
    report = world.run([(TrashNothingAdapter.from_fixture(FIX / "trashnothing", world.clock), TN)])
    s = report.sources[0]
    assert (s.fetched, s.created, s.quarantined) == (5, 4, 1)        # 2 pages; the WANTED post is quarantined
    items = _by_listing(world)
    mower = items["40000001"]
    assert mower["category"] == "mower" and mower["opportunity_kind"] == "free_item"
    n = mower["normalized"]
    assert n["title"] == "Push mower, needs carb"                     # "OFFER:" prefix and "(place)" suffix stripped
    assert n["price"] == {"amount": 0, "currency": "USD", "type": "free"}
    assert {"free", "needs_review"} <= set(n["flags"])
    assert n["location"]["geo_tier"] == 0
    assert items["40000002"]["normalized"]["listing_status"] == "gone"    # outcome: satisfied
    assert "injection_suspected" in items["40000003"]["normalized"]["flags"]
    assert items["40000004"]["category"] == "compressor"
    blob = json.dumps(list(world.store.items.values()))
    assert "u-fixture" not in blob and "Group rule" not in blob       # user_id / footer stay in raw only
    for i in world.store.items.values():
        contract.check_item(i)


def test_trashnothing_api_key_redacted_from_provenance(world):
    world.run([(TrashNothingAdapter.from_fixture(FIX / "trashnothing", world.clock), TN)])
    for prov in world.store.provenance.values():
        for used in prov["inputs_used"]:
            assert "api_key" not in used["ref"] and "fixture-key" not in used["ref"]


def test_trashnothing_request_shape_and_radius_cap():
    seen = []

    def handler(m, u, h, b):
        seen.append(u)
        return HttpResponse(200, b'{"posts":[],"num_pages":1}')

    TrashNothingAdapter("K", live=True, transport=CallbackTransport(handler)).fetch(FLIP)
    q = parse_qs(urlsplit(seen[0]).query)
    assert q["types"] == ["offer"] and q["sources"] == ["groups,trashnothing"]
    assert q["radius"] == ["80500"]                                    # 100 mi capped at the API max (meters)
    assert q["api_key"] == ["K"] and len(seen) == 1


def test_trashnothing_requires_explicit_live_enablement():
    calls = []
    t = CallbackTransport(lambda *a: calls.append(a))
    assert TrashNothingAdapter("k", transport=t).fetch(TN).error.kind == "config"
    assert TrashNothingAdapter(None, live=True, transport=t).fetch(TN).error.kind == "config"
    assert calls == []


def test_new_adapters_repeat_without_duplicates(world):
    jobs = [(GsaAuctionsAdapter.from_fixture(FIX / "gsa", world.clock), GSA),
            (TrashNothingAdapter.from_fixture(FIX / "trashnothing", world.clock), TN)]
    world.run(jobs)
    n = len(world.store.items)
    world.clock.advance(hours=1)
    r = world.run(jobs)
    assert len(world.store.items) == n and all(s.created == s.merged == s.updated == 0 for s in r.sources)


def test_new_adapters_replay_from_raw(world):
    from mbos_discovery.ids import parse_ts
    ads = {"gsa_auctions": GsaAuctionsAdapter.from_fixture(FIX / "gsa", world.clock),
           "trashnothing": TrashNothingAdapter.from_fixture(FIX / "trashnothing", world.clock)}
    world.run([(ads["gsa_auctions"], GSA), (ads["trashnothing"], TN)])
    for item in world.store.items.values():
        s0 = item["sources"][0]
        prov = world.store.provenance[s0["provenance_id"]]
        n = ads[s0["source"]].normalize(json.loads(world.raw.get(s0["raw_ref"])), parse_ts(prov["fetched_at"]))
        assert n.normalized == item["normalized"]
