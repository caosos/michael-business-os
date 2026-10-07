"""B-01: lane-B adapters behind Agent 01's `mbos.interfaces`, run through the real `mbos.spine.ingest`
on PostgreSQL 16 (pgserver). Skipped when the `mbos` spine is not installed (see
docs/implementation/agent-02-discovery-lane.md §9 for the pinned install)."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

os.environ.setdefault("MBOS_CONTRACTS_DIR", str(Path(__file__).parent / "fixtures" / "mbos_contracts_99e9ec0"))
pytest.importorskip("mbos")

import sqlalchemy as sa  # noqa: E402

from conftest import FIX, FLIP, SERVICE, Clock, StaticAdapter  # noqa: E402
from mbos.hashing import canonical_json as spine_cjson, sha256_bytes  # noqa: E402
from mbos.interfaces import Deduper, NormalizedListing, Normalizer, RawListing, SourceAdapter  # noqa: E402
from mbos_discovery.adapter import SourceError  # noqa: E402
from mbos_discovery.adapters import EbayBrowseAdapter, ServiceIntakeAdapter  # noqa: E402
from mbos_discovery.spine import SpineDeduper, discovery_components  # noqa: E402


def _jobs(clock, intake_root=FIX / "intake"):
    return [
        (EbayBrowseAdapter.from_fixture(FIX / "ebay", clock), FLIP),
        (ServiceIntakeAdapter("website_lead", intake_root / "website_form", clock), SERVICE),
        (ServiceIntakeAdapter("referral", intake_root / "referral", clock), SERVICE),
    ]


@pytest.fixture
def lane(tmp_path):
    clock = Clock()
    adapters, normalizer, deduper, side = discovery_components(
        _jobs(clock), raw_dir=tmp_path / "raw", side_path=tmp_path / "side.jsonl",
        health_path=tmp_path / "health.json", clock=clock)
    return adapters, normalizer, deduper, side, tmp_path


# ---------------------------------------------------------------- protocol level (no database)
def test_components_satisfy_spine_protocols(lane):
    adapters, normalizer, deduper, _, _ = lane
    assert all(isinstance(a, SourceAdapter) for a in adapters.values())
    assert isinstance(normalizer, Normalizer) and isinstance(deduper, Deduper)
    assert set(adapters) == {"ebay:flip-test", "website_lead:service-test", "referral:service-test"}


def test_fetch_emits_checkpointable_rawlistings(lane):
    adapters, normalizer, *_ = lane
    for a in adapters.values():
        for r in a.fetch():
            d = asdict(r)
            assert RawListing(**json.loads(json.dumps(d))) == r          # survives a DBOS checkpoint
            n = normalizer.normalize(r)
            nd = json.loads(json.dumps(asdict(n)))
            assert NormalizedListing(**nd) == n
            assert r.source_listing_id and r.url and r.fetched_at.endswith("Z")


def test_raw_ref_is_hash_of_the_same_stored_bytes_in_both_lanes(lane):
    adapters, _, _, _, tmp = lane
    from mbos_discovery.rawstore import FileRawStore
    ours = FileRawStore(tmp / "raw")
    n = 0
    for a in adapters.values():
        for r in a.fetch():
            spine_bytes = spine_cjson(r.payload)                       # what mbos.spine.ingest stores
            assert ours.get(sha256_bytes(spine_bytes)) == spine_bytes  # we retained identical bytes
            n += 1
    assert n == 11                                     # 6 eBay + 3 web + 2 referral (1 quarantined)


def test_normalizer_is_deterministic(lane):
    adapters, normalizer, *_ = lane
    raws = [r for a in adapters.values() for r in a.fetch()]
    assert [normalizer.normalize(r) for r in raws] == [normalizer.normalize(r) for r in raws]


def test_service_blocking_key_uses_contact_fingerprint_not_contact(lane):
    adapters, normalizer, *_ = lane
    keys = [normalizer.normalize(r).dedup_key for r in adapters["website_lead:service-test"].fetch()]
    assert all("|lead|fp-" in k for k in keys)
    assert not any("example.invalid" in k or "555" in k for k in keys)


def test_deduper_rules():
    d = SpineDeduper()
    flip = {"type": "flip", "category": "trailer", "state": "NORMALIZED",
            "normalized": {"title": "6x12 enclosed utility trailer", "price": {"amount": 1200},
                           "location": {"city": "Conway", "state": "AR"}}}
    same = NormalizedListing("flip", "trailer", "k", {"title": "Enclosed utility trailer 6x12",
                             "price": {"amount": 1150}, "location": {"city": "Conway", "state": "AR"}})
    other = NormalizedListing("flip", "trailer", "k", {"title": "dump trailer 7x14 hydraulic",
                              "price": {"amount": 1200}, "location": {"city": "Conway", "state": "AR"}})
    assert d.is_duplicate(flip, same) and not d.is_duplicate(flip, other)
    assert not d.is_duplicate({**flip, "category": "mower"}, same)
    lead = {"type": "service", "category": "drywall_repair", "dedup_key": "drywall_repair|lead|fp-abc", "state": "RESEARCHING"}
    cand = NormalizedListing("service", "drywall_repair", "drywall_repair|lead|fp-abc", {"title": "x"})
    assert d.is_duplicate(lead, cand)
    assert not d.is_duplicate({**lead, "state": "ACTED"}, cand)          # finished job → new work
    geo = NormalizedListing("service", "drywall_repair", "drywall_repair|lead|zip-720", {"title": "x"})
    assert not d.is_duplicate({**lead, "dedup_key": geo.dedup_key}, geo)  # no contact → never merge


# ---------------------------------------------------------------- side channel (R5) and safety
def test_failures_go_to_side_channel_and_fetch_never_raises(tmp_path):
    clock = Clock()
    jobs = [(StaticAdapter("craigslist", [SourceError("rate_limited", "429", 429)], clock), FLIP),
            (StaticAdapter("facebook_marketplace", [[]], clock), FLIP),
            (StaticAdapter("craigslist", [RuntimeError("bug")], clock), FLIP.__class__("p2", "flip"))]
    adapters, _, _, side = discovery_components(jobs, raw_dir=tmp_path / "raw", enabled_sources=frozenset({"craigslist"}),
                                                health_path=tmp_path / "h.json", clock=clock)
    rl = adapters["craigslist:flip-test"]
    assert rl.fetch() == [] and rl.fetch() == []
    assert side.freeze_requests()[0]["capability"] == "discovery.source.craigslist.read"
    assert rl.fetch() == [] and side.events[-1]["reason"].startswith("source FROZEN")
    fb = adapters["facebook_marketplace:flip-test"]
    assert fb.fetch() == [] and fb.inner.fetch_calls == 0
    assert any(e["kind"] == "skipped" and "do-not-automate" in e["reason"] for e in side.events)
    assert json.loads((tmp_path / "h.json").read_text())["craigslist"]["status"] == "FROZEN"   # persisted


def test_malformed_record_quarantined_with_raw_kept(lane):
    adapters, _, _, side, tmp = lane
    out = adapters["referral:service-test"].fetch()
    assert {r.source_listing_id for r in out} == {"ref-0001", "ref-0002"}
    q = [e for e in side.events if e["kind"] == "quarantine"]
    assert len(q) == 1
    from mbos_discovery.rawstore import FileRawStore
    assert FileRawStore(tmp / "raw").get(q[0]["raw_ref"]).startswith(b'{"submission_id": "ref-bad"')
    assert (tmp / "side.jsonl").read_text().count('"quarantine"') == 1


# ---------------------------------------------------------------- through the real spine (Postgres)
@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pg")), cleanup_mode="stop")
    yield server
    server.cleanup()


@pytest.fixture
def spine_db(pg):
    from mbos.config import Settings, configure
    from mbos.db.engine import engine_for
    from mbos.db.migrate import migrate

    name = f"b01_{uuid.uuid4().hex[:10]}"
    pg.psql(f"CREATE DATABASE {name};")
    url = pg.get_uri().replace("/postgres?", f"/{name}?")
    configure(Settings(database_url=url, system_database_url=url))
    engine = engine_for(url)
    migrate(engine)
    yield engine
    engine.dispose()


def _ingest_all(engine, comps):
    from mbos import spine
    results = []
    for name, a in comps.adapters.items():
        for raw in a.fetch():
            norm = comps.normalizer.normalize(raw)
            with engine.begin() as c:
                results.append(spine.ingest(c, asdict(raw), asdict(norm) if norm else None, name, a.version, comps))
    return results


def _components(tmp_path, clock, extra_jobs=(), enabled=frozenset()):
    from mbos.runtime import Components
    adapters, normalizer, deduper, side = discovery_components(
        _jobs(clock) + list(extra_jobs), raw_dir=tmp_path / "raw", enabled_sources=enabled, clock=clock)
    return Components(adapters=adapters, normalizer=normalizer, deduper=deduper).with_defaults(), side


def _items(engine):
    with engine.connect() as c:
        return [r.body for r in c.execute(sa.text("SELECT body FROM mbos.items ORDER BY item_id"))]


def test_fixtures_through_real_spine_identity_first(spine_db, tmp_path):
    clock = Clock()
    comps, side = _components(tmp_path, clock)
    r1 = _ingest_all(spine_db, comps)
    items = _items(spine_db)
    assert sum(r["created"] for r in r1) == 10 and sum(r["merged"] for r in r1) == 1   # drywall lead merged
    assert len(items) == 10
    assert {i["type"] for i in items} == {"flip", "service"}
    assert all(i["state"] == "NORMALIZED" for i in items)
    # every sighting's raw_ref is in the spine's artifact store AND in ours, with identical bytes
    from mbos_discovery.rawstore import FileRawStore
    ours = FileRawStore(tmp_path / "raw")
    with spine_db.connect() as c:
        for i in items:
            assert i["sources"]
            for s in i["sources"]:
                stored = c.execute(sa.text("SELECT content FROM mbos.artifacts WHERE sha256 = :h"),
                                   {"h": s["raw_ref"]}).scalar_one()
                assert bytes(stored) == ours.get(s["raw_ref"])
    # repeated discovery: identity-first → no new items, no merges
    clock.advance(hours=1)
    r2 = _ingest_all(spine_db, comps)
    assert not any(r["created"] or r["merged"] for r in r2)
    assert len(_items(spine_db)) == 10


def test_cross_source_merge_through_real_spine(spine_db, tmp_path):
    clock = Clock()
    mirror = StaticAdapter("craigslist", [[{"id": "cl-1", "title": "6x12 enclosed utility trailer needs lights and floor",
                                            "price": 1150, "city": "Conway", "state": "AR", "zip": "72034"}]], clock)
    comps, _ = _components(tmp_path, clock, [(mirror, FLIP)], enabled=frozenset({"craigslist"}))
    _ingest_all(spine_db, comps)
    trailer = [i for i in _items(spine_db) if {s["source"] for s in i["sources"]} >= {"ebay", "craigslist"}]
    assert len(trailer) == 1 and len(trailer[0]["sources"]) == 2


def test_blocking_key_collision_without_match_does_not_merge(spine_db, tmp_path):
    clock = Clock()
    lookalike = StaticAdapter("craigslist", [[{"id": "cl-9", "title": "Aluminum boat trailer, single axle",
                                               "price": 1100, "city": "Conway", "state": "AR", "zip": "72034"}]], clock)
    comps, _ = _components(tmp_path, clock, [(lookalike, FLIP)], enabled=frozenset({"craigslist"}))
    res = _ingest_all(spine_db, comps)
    assert res[-1]["created"] and not res[-1]["merged"]
    trailers = [i for i in _items(spine_db) if i["category"] == "trailer"]
    boat = next(i for i in trailers if i["sources"][0]["source"] == "craigslist")
    assert any(t["dedup_key"] == boat["dedup_key"] for t in trailers if t is not boat)   # keys really collide
    assert len(trailers) == 4
