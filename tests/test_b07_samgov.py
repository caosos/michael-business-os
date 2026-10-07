"""B-07: SAM.gov Get Opportunities v2 → service-lane `gov_contract` leads; fixture-first, read-only, explicit live
switch, API key never recorded."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from conftest import FIX, World
from mbos_discovery import contract
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import SamGovAdapter
from mbos_discovery.http import CallbackTransport, HttpResponse
from mbos_discovery.ids import parse_ts

GOV = SearchProfile("service-gov", "service", limit=50)


def _items(world):
    return {s["source_listing_id"]: i for i in world.store.items.values() for s in i["sources"]}


def test_fixture_run_maps_naics_and_fields(world):
    r = world.run([(SamGovAdapter.from_fixture(FIX / "samgov", world.clock), GOV)]).sources[0]
    assert (r.fetched, r.created, r.quarantined) == (5, 4, 1)
    it = _items(world)
    eq = it["fx0001aa"]
    assert (eq["type"], eq["category"], eq["opportunity_kind"], eq["subcategory"]) == (
        "service", "equipment_repair", "gov_contract", "NAICS 811310")
    n = eq["normalized"]
    assert n["price"] == {"type": "quote_requested"} and n["listing_status"] == "open"
    assert n["ends_at"] == "2026-10-20T19:00:00Z"                         # -05:00 → UTC
    assert n["location"] == {"city": "Conway", "state": "AR", "zip": "72034"}
    assert n["counterparty"] == {"role": "agency", "contact_method": "gov_poc",
                                 "name": "DEPT OF DEFENSE.DEPT OF THE ARMY.USACE"}
    assert "Total Small Business Set-Aside" in n["description"]
    assert it["fx0002bb"]["category"] == "drywall_repair" and "ending_soon" in it["fx0002bb"]["normalized"]["flags"]
    assert it["fx0003cc"]["category"] == "smart_home_install"           # unknown NAICS → keyword rules
    assert it["fx0004dd"]["category"] == "other_service" and it["fx0004dd"]["normalized"]["listing_status"] == "closed"
    assert "needs_review" in it["fx0004dd"]["normalized"]["flags"]
    blob = json.dumps(list(world.store.items.values()))
    assert "co@example.invalid" not in blob and "5015550100" not in blob   # PoC stays in raw only
    for i in world.store.items.values():
        contract.check_item(i)


def test_requires_live_flag_and_key():
    calls = []
    t = CallbackTransport(lambda *a: calls.append(a))
    assert SamGovAdapter("k", transport=t).fetch(GOV).error.kind == "config"
    assert SamGovAdapter(None, live=True, transport=t).fetch(GOV).error.kind == "config"
    assert calls == []


def test_request_shape_one_call_per_state_and_key_redacted(world):
    seen = []

    def handler(m, u, h, b):
        seen.append(u)
        return HttpResponse(200, b'{"opportunitiesData":[{"noticeId":"x1","title":"Generator repair","naicsCode":"811310"}]}')

    ad = SamGovAdapter("SECRET", live=True, states=("AR", "MO"), transport=CallbackTransport(handler), clock=world.clock)
    world.run([(ad, GOV)])
    assert len(seen) == 2
    q = parse_qs(urlsplit(seen[0]).query)
    assert (q["postedFrom"], q["postedTo"], q["ptype"], q["state"], q["api_key"]) == (
        ["09/23/2026"], ["10/07/2026"], ["o,k,p,r"], ["AR"], ["SECRET"])
    for prov in world.store.provenance.values():
        assert "SECRET" not in json.dumps(prov)
    assert all("SECRET" not in u for _, u, _ in ad.http.log)


def test_replay_repeat_and_rate_limit_freeze(world):
    ad = SamGovAdapter.from_fixture(FIX / "samgov", world.clock)
    world.run([(ad, GOV)])
    for item in world.store.items.values():
        s0 = item["sources"][0]
        prov = world.store.provenance[s0["provenance_id"]]
        assert ad.normalize(json.loads(world.raw.get(s0["raw_ref"])), parse_ts(prov["fetched_at"])).normalized == item["normalized"]
    world.clock.advance(hours=1)
    assert world.run([(ad, GOV)]).sources[0].created == 0
    limited = SamGovAdapter("k", live=True, clock=world.clock, transport=CallbackTransport(lambda *a: HttpResponse(429, b"x")))
    world.run([(limited, GOV)])
    assert world.run([(limited, GOV)]).freeze_requests[0]["capability"] == "discovery.source.samgov.read"


def test_flip_profile_is_not_served():
    w = World()
    r = w.run([(SamGovAdapter.from_fixture(FIX / "samgov", w.clock), SearchProfile("f", "flip"))]).sources[0]
    assert r.status == "skipped" and "lane" in r.skipped_reason
