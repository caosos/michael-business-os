"""Repeated discovery never creates duplicate Items; cross-source duplicates merge."""

import json

from conftest import FIX, FLIP, SERVICE, StaticAdapter, World
from mbos_discovery.adapters import EbayBrowseAdapter, ServiceIntakeAdapter
from mbos_discovery.http import CallbackTransport, HttpResponse


def test_repeated_discovery_creates_no_duplicates(world):
    world.run()
    n_items, n_events, n_prov = len(world.store.items), len(world.store.events), len(world.store.provenance)
    first_seen = {i: [s["first_seen_at"] for s in it["sources"]] for i, it in world.store.items.items()}
    for _ in range(3):
        world.clock.advance(minutes=30)
        report = world.run()
        assert all(s.created == 0 and s.merged == 0 and s.updated == 0 for s in report.sources)
    assert len(world.store.items) == n_items
    assert len(world.store.events) == n_events            # no new receipt intents for unchanged listings
    assert len(world.store.provenance) == n_prov
    for iid, item in world.store.items.items():
        assert [s["first_seen_at"] for s in item["sources"]] == first_seen[iid]
        assert all(s["last_seen_at"] == "2026-10-07T13:30:00Z" for s in item["sources"])


def test_same_listing_from_two_queries_is_one_item(world):
    world.run()
    hits = [i for i in world.store.items.values()
            if any(s.get("source_listing_id") == "v1|110000000001|0" for s in i["sources"])]
    assert len(hits) == 1 and len(hits[0]["sources"]) == 1


def test_pagination_followed(world):
    world.run()
    ids = {s["source_listing_id"] for i in world.store.items.values() for s in i["sources"]}
    assert "v1|110000000003|0" in ids                      # only on page 2


def _ebay_with_price(world, new_price):
    base = FIX / "ebay"

    def handler(method, url, headers, body):
        if method == "POST":
            return HttpResponse(200, (base / "token.json").read_bytes())
        if "utility+trailer" in url and "offset=0" in url:
            data = json.loads((base / "search-utility-trailer.json").read_text())
            data["itemSummaries"][0]["price"]["value"] = new_price
            data.pop("next")
            return HttpResponse(200, json.dumps(data).encode())
        return HttpResponse(200, b'{"itemSummaries":[]}')

    return EbayBrowseAdapter("id", "secret", transport=CallbackTransport(handler), clock=world.clock)


def test_source_side_change_updates_in_place(world):
    world.run([(_ebay_with_price(world, "1200.00"), FLIP)])
    (iid, item), = [(i, it) for i, it in world.store.items.items()
                    if it["sources"][0]["source_listing_id"] == "v1|110000000001|0"]
    old_raw = item["sources"][0]["raw_ref"]
    world.clock.advance(hours=2)
    report = world.run([(_ebay_with_price(world, "999.00"), FLIP)])
    assert report.sources[0].updated == 1 and report.sources[0].created == 0
    item = world.store.items[iid]
    assert item["normalized"]["price"]["amount"] == 999.0
    assert "price_changed" in item["normalized"]["flags"]
    assert item["sources"][0]["raw_ref"] != old_raw
    assert world.raw.exists(old_raw)                        # history retained, immutable
    assert len(item["provenance_ids"]) == 2
    assert item["sources"][0]["first_seen_at"] == "2026-10-07T12:00:00Z"


def test_cross_source_duplicate_merges_as_sighting(world):
    mirror = StaticAdapter("craigslist", [[
        {"id": "cl-1", "title": "6x12 enclosed utility trailer needs lights and floor", "price": 1150,
         "city": "Conway", "state": "AR", "zip": "72034"},
        {"id": "cl-2", "title": "Craftsman riding mower", "price": 400, "city": "Conway", "state": "AR",
         "zip": "72034"},
    ]], world.clock)
    jobs = world.jobs()[:1] + [(mirror, FLIP)]
    report = world.run(jobs, enabled=frozenset({"craigslist"}))
    cl = report.sources[1]
    assert (cl.merged, cl.created) == (1, 1)
    merged = [i for i in world.store.items.values() if len(i["sources"]) == 2]
    assert len(merged) == 1
    assert {s["source"] for s in merged[0]["sources"]} == {"ebay", "craigslist"}
    assert all(s["raw_ref"] for s in merged[0]["sources"])
    # repeat: still merged, nothing new
    world.clock.advance(hours=1)
    report = world.run(jobs, enabled=frozenset({"craigslist"}))
    assert sum(s.created + s.merged for s in report.sources) == 0


def test_same_source_lookalikes_are_not_merged(world):
    twins = StaticAdapter("craigslist", [[
        {"id": "a", "title": "Honda EU2200i generator", "price": 800, "city": "Conway", "state": "AR"},
        {"id": "b", "title": "Honda EU2200i generator", "price": 800, "city": "Conway", "state": "AR"},
    ]], world.clock)
    world.run([(twins, FLIP)], enabled=frozenset({"craigslist"}))
    assert len(world.store.items) == 2                     # a dealer can list two identical units


def test_service_lead_seen_twice_merges_by_contact(world):
    world.run()
    drywall = [i for i in world.store.items.values() if i["category"] == "drywall_repair"]
    assert len(drywall) == 1
    assert {s["source"] for s in drywall[0]["sources"]} == {"website_lead", "referral"}
    # contact details never appear in the Item
    blob = json.dumps(drywall[0])
    assert "example.invalid" not in blob.replace("intake://", "") and "555" not in blob


def test_service_dedup_window(tmp_path):
    inbox = tmp_path / "web"
    inbox.mkdir()
    lead = {"submission_id": "w1", "received_at": "2026-10-01T00:00:00Z", "service_requested": "Drywall patch",
            "email": "a@example.invalid"}
    (inbox / "w1.json").write_text(json.dumps(lead))
    w = World()
    w.run([(ServiceIntakeAdapter("website_lead", inbox, w.clock), SERVICE)])
    w.clock.advance(days=30)
    (inbox / "w2.json").write_text(json.dumps({**lead, "submission_id": "w2", "received_at": "2026-11-06T00:00:00Z"}))
    w.run([(ServiceIntakeAdapter("website_lead", inbox, w.clock), SERVICE)])
    assert len(w.store.items) == 2                         # a month later it's a new job
