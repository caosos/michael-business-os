"""B-15: `listing_activity` + `seller` enrichment blocks for the Deal Sniffer card (ADR-0011).
Only what the source exposes; never inferred seller data; nothing fabricated; blocks render on the real card."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import FIX, FLIP, T0, World
from mbos_discovery.adapters import EbayBrowseAdapter
from mbos_discovery.enrichment import build_blocks, exposed_facts

PROV = "prov_" + "0" * 26
OWN = "prov_" + "1" * 26
AS_OF = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
EXTRA = json.loads((FIX / "enrichment_sources.json").read_text())


def _item(source, lid, **kw):
    return {"item_id": "itm_x", "type": "flip", "category": "trailer", "opportunity_kind": kw.pop("kind", "buy_item"),
            "sources": kw.pop("sources", [{"source": source, "source_listing_id": lid, "url": "https://x.invalid/1",
                                           "first_seen_at": "2026-10-04T12:00:00Z", "raw_ref": "sha256:" + "a" * 64,
                                           "provenance_id": PROV}]), **kw}


def _ebay_payload():
    return json.loads((FIX / "ebay" / "search-utility-trailer.json").read_text())["itemSummaries"][0]


# ---------------------------------------------------------------- what each source exposes
def test_ebay_exposes_real_dates_and_feedback():
    f = exposed_facts("ebay", _ebay_payload())
    assert f == {"posted_at": "2026-09-12T15:04:05Z", "rating": {"feedback_percent": 98.6, "feedback_score": 412}}


def test_other_sources_expose_only_what_they_say():
    assert exposed_facts("gsa_auctions", {"AucStartDt": "2026-10-01"}) == {"posted_at": "2026-10-01T00:00:00Z"}
    assert exposed_facts("trashnothing", {"date": "2026-10-06T18:00:00", "repost_count": 2}) == {
        "posted_at": "2026-10-06T18:00:00Z", "repost_count": 2}
    assert exposed_facts("ebay", {"itemId": "x", "seller": {"username": "u", "sellerAccountType": "BUSINESS"}}) == {}


def test_sources_without_an_adapter_expose_nothing_even_with_tempting_text():
    for src in ("craigslist", "facebook_marketplace", "some_new_site"):
        assert exposed_facts(src, EXTRA.get(src, {"seller": "Bob", "posted": "yesterday"})) == {}


# ---------------------------------------------------------------- blocks
def test_ebay_blocks_have_real_dates_seller_feedback_and_provenance():
    item = _item("ebay", "L1")
    facts = {"ebay|L1": exposed_facts("ebay", _ebay_payload())}
    b = build_blocks(item, facts, AS_OF, OWN)
    la, sel = b["listing_activity"], b["seller"]
    assert la["posted_at"] == {"value": "2026-09-12T15:04:05Z", "basis": "FACT", "provenance_id": PROV,
                               "note": "as reported by ebay"}
    assert la["age_days"]["value"] == 24 and la["age_days"]["provenance_id"] == OWN
    assert la["stale_risk"]["value"] == "medium" and la["stale_risk"]["basis"] == "INFERENCE"
    assert "listed 24 days ago" in la["stale_risk"]["note"]
    assert "Listed 24 days ago (ebay)" in la["recent_activity"]
    assert "updated_at" not in la                                         # eBay Browse exposes no edit date
    assert sel["rating"]["value"] == {"feedback_percent": 98.6, "feedback_score": 412}
    assert sel["rating"]["basis"] == "FACT" and sel["rating"]["provenance_id"] == PROV
    assert sel["confidence"] == "low"
    for k in ("account_age", "prior_listings", "complaint_signals", "response_history", "inconsistencies"):
        assert k not in sel                                               # not exposed → omitted → card says UNKNOWN


def test_no_adapter_sources_give_empty_seller_and_no_fabricated_dates():
    for src in ("craigslist", "facebook_marketplace"):
        item = _item(src, "9")
        b = build_blocks(item, {f"{src}|9": exposed_facts(src, EXTRA[src])}, AS_OF, OWN)
        assert b["seller"] == {}
        la = b["listing_activity"]
        assert not ({"posted_at", "updated_at", "age_days", "stale_risk", "suspected_relist"} & set(la))
        assert all("trusted" not in a and "weeks" not in a for a in la["recent_activity"])


def test_first_seen_is_our_observation_never_a_listing_age():
    b = build_blocks(_item("craigslist", "9"), {}, AS_OF, OWN)["listing_activity"]
    assert "age_days" not in b and "posted_at" not in b and "stale_risk" not in b
    assert b["recent_activity"] == ["First seen by this system 3 days ago (craigslist)"]


def test_future_dates_are_dropped_not_trusted():
    item = _item("ebay", "L1")
    b = build_blocks(item, {"ebay|L1": {"posted_at": "2026-12-01T00:00:00Z"}}, AS_OF, OWN)["listing_activity"]
    assert "posted_at" not in b and "age_days" not in b


def test_relist_is_inferred_only_from_two_listing_ids_and_raises_staleness():
    sightings = [{"source": "ebay", "source_listing_id": i, "url": "u", "first_seen_at": "2026-09-30T00:00:00Z",
                  "raw_ref": "sha256:" + "a" * 64, "provenance_id": PROV} for i in ("A", "B")]
    item = _item("ebay", "A", sources=sightings)
    facts = {"ebay|A": {"posted_at": "2026-09-20T00:00:00Z"}, "ebay|B": {"posted_at": "2026-10-03T00:00:00Z"}}
    la = build_blocks(item, facts, AS_OF, OWN)["listing_activity"]
    assert la["suspected_relist"]["value"] is True and la["suspected_relist"]["basis"] == "INFERENCE"
    assert la["posted_at"]["value"] == "2026-09-20T00:00:00Z"            # earliest exposed date
    assert la["stale_risk"]["value"] == "high" and "re-posted" in la["stale_risk"]["note"]   # 17 d → medium → +1
    single = build_blocks(_item("ebay", "A"), {"ebay|A": facts["ebay|A"]}, AS_OF, OWN)["listing_activity"]
    assert "suspected_relist" not in single                               # "not a relist" is never asserted


def test_auctions_get_no_stale_risk():
    la = build_blocks(_item("gsa_auctions", "S-1", kind="auction_lot"),
                      {"gsa_auctions|S-1": {"posted_at": "2026-08-01T00:00:00Z"}}, AS_OF, OWN)["listing_activity"]
    assert la["age_days"]["value"] == 67 and "stale_risk" not in la


def test_price_movement_comes_only_from_our_observations():
    hist = [{"source": "ebay", "listing_id": "L1", "at": "2026-10-04T12:00:00Z", "price": 1200.0},
            {"source": "ebay", "listing_id": "L1", "at": "2026-10-06T12:00:00Z", "price": 999.0}]
    la = build_blocks(_item("ebay", "L1"), {}, AS_OF, OWN, hist)["listing_activity"]
    assert "Price dropped 1200 → 999 (observed 1 day ago)" in la["recent_activity"]


def test_deterministic_and_json_clean():
    item = _item("ebay", "L1")
    facts = {"ebay|L1": exposed_facts("ebay", _ebay_payload())}
    a, b = build_blocks(item, facts, AS_OF, OWN), build_blocks(item, facts, AS_OF, OWN)
    assert a == b and json.loads(json.dumps(a)) == a


# ---------------------------------------------------------------- end to end on the real spine + card
pytest.importorskip("mbos")
pytest.importorskip("pgserver")
os.environ.setdefault("MBOS_CONTRACTS_DIR", str(FIX / "mbos_contracts_99e9ec0"))

import sqlalchemy as sa  # noqa: E402


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    import pgserver
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pg15")), cleanup_mode="stop")
    yield server
    server.cleanup()


@pytest.fixture
def spine_db(pg):
    from mbos.config import Settings, configure
    from mbos.db.engine import engine_for
    from mbos.db.migrate import migrate
    name = f"b15_{uuid.uuid4().hex[:10]}"
    pg.psql(f"CREATE DATABASE {name};")
    url = pg.get_uri().replace("/postgres?", f"/{name}?")
    configure(Settings(database_url=url, system_database_url=url))
    engine = engine_for(url)
    migrate(engine)
    yield engine
    engine.dispose()


def _ingest_ebay(engine, tmp_path, clock):
    from mbos import spine
    from mbos.runtime import Components
    from mbos_discovery.spine import discovery_components
    prof = FLIP.__class__("p", "flip", ("utility trailer",), limit=2, max_pages=2)
    adapters, normalizer, deduper, _ = discovery_components(
        [(EbayBrowseAdapter.from_fixture(FIX / "ebay", clock), prof)], raw_dir=tmp_path / "raw", clock=clock)
    comps = Components(adapters=adapters, normalizer=normalizer, deduper=deduper).with_defaults()
    ids = {}
    for name, a in adapters.items():
        for raw in a.fetch():
            norm = normalizer.normalize(raw)
            with engine.begin() as c:
                r = spine.ingest(c, asdict(raw), asdict(norm), name, a.version, comps)
            ids[raw.source_listing_id] = r["item_id"]
    return ids


def _card(engine, spine, item_id):
    import mbos.card as card
    with engine.connect() as c:
        item, receipts, areqs = card.load_inputs(c, item_id)
        enr = card.enrichment_from_item(c, item)
    built = card.build_card(item, receipts, areqs, enr, now=AS_OF,
                            profile=card.load_profile(FIX / "operator_profile.v1.json"))
    return built, card.validate_card(built), enr


def test_blocks_attach_and_render_on_the_card(spine_db, tmp_path):
    from mbos import spine
    from mbos_discovery.enrichment import attach_enrichment
    from mbos_discovery.rawstore import FileRawStore
    from conftest import Clock
    ids = _ingest_ebay(spine_db, tmp_path, Clock())
    item_id = ids["v1|110000000001|0"]
    raw = FileRawStore(tmp_path / "raw")
    with spine_db.begin() as c:
        out = attach_enrichment(c, spine, item_id, raw, AS_OF)
    assert sorted(out["attached"]) == ["listing_activity", "seller"]
    card, errors, enr = _card(spine_db, spine, item_id)
    assert errors == []                                                    # passes the card schema + honesty lint
    la, sel = card["listing_activity"], card["seller"]
    assert la["posted_at"]["value"] == "2026-09-12T15:04:05Z" and la["age_days"]["value"] == 24
    assert la["updated_at"]["value"] == "UNKNOWN" and la["suspected_relist"]["value"] == "UNKNOWN"
    assert sel["rating"]["value"]["feedback_percent"] == 98.6 and sel["confidence"] == "low"
    for k in ("account_age", "prior_listings", "complaint_signals", "response_history", "inconsistencies"):
        assert sel[k]["value"] == "UNKNOWN"
    assert "seller.account_age" in card["unknowns"] and "listing_activity.updated_at" in card["unknowns"]
    with spine_db.connect() as c:                                          # own provenance recorded, receipted
        prov = c.execute(sa.text("SELECT body FROM mbos.provenance WHERE body->>'provenance_id' = :p"),
                         {"p": out["provenance_id"]}).scalar_one()
    assert prov["agent_name"] == "agent-02-opportunity" and prov["tool_name"] == "mbos_discovery.enrichment"
    # idempotent
    with spine_db.begin() as c:
        again = attach_enrichment(c, spine, item_id, raw, AS_OF)
    assert again["attached"] == []


def test_item_without_seller_data_attaches_no_seller_block_and_card_says_unknown(spine_db, tmp_path):
    from mbos import spine
    from mbos_discovery.enrichment import attach_enrichment
    from mbos_discovery.rawstore import FileRawStore
    from conftest import Clock
    ids = _ingest_ebay(spine_db, tmp_path, Clock())
    item_id = ids["v1|110000000003|0"]                                      # fixture listing with no seller/date fields
    with spine_db.begin() as c:
        out = attach_enrichment(c, spine, item_id, FileRawStore(tmp_path / "raw"), AS_OF)
    assert "seller" not in out["attached"]
    card, errors, enr = _card(spine_db, spine, item_id)
    assert errors == [] and "seller" not in enr
    assert card["seller"]["rating"]["value"] == "UNKNOWN" and card["seller"]["confidence"] == "UNKNOWN"
    assert card["listing_activity"]["posted_at"]["value"] == "UNKNOWN"
