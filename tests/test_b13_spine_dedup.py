"""B-13: lane B's relist + pHash rules on the SPINE path (A-14 Deduper context @ agent-01 a910ad9).
Acceptance: 02's 7-day corpus through 01's spine `ingest` → F2 0.00% missed, 0 false merges."""

from __future__ import annotations

import os
import uuid
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import pytest

os.environ.setdefault("MBOS_CONTRACTS_DIR", str(Path(__file__).parent / "fixtures" / "mbos_contracts_99e9ec0"))
pytest.importorskip("mbos")
pytest.importorskip("pgserver")
pytest.importorskip("PIL")

import json  # noqa: E402

import sqlalchemy as sa  # noqa: E402

from conftest import FIX  # noqa: E402
from mbos.interfaces import Deduper, NormalizedListing  # noqa: E402
from mbos_discovery.acceptance import T0, _Clock, _corpus_jobs, check_f2, image_fetcher  # noqa: E402
from mbos_discovery.spine import SpineDeduper, discovery_components  # noqa: E402

CORPUS = FIX / "corpus7d"


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    import pgserver
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pg13")), cleanup_mode="stop")
    yield server
    server.cleanup()


@pytest.fixture
def spine_db(pg):
    from mbos.config import Settings, configure
    from mbos.db.engine import engine_for
    from mbos.db.migrate import migrate
    name = f"b13_{uuid.uuid4().hex[:10]}"
    pg.psql(f"CREATE DATABASE {name};")
    url = pg.get_uri().replace("/postgres?", f"/{name}?")
    configure(Settings(database_url=url, system_database_url=url))
    engine = engine_for(url)
    migrate(engine)
    yield engine
    engine.dispose()


def _run_corpus_through_spine(engine, tmp_path, with_images: bool):
    from mbos import spine
    from mbos.runtime import Components
    fetcher = image_fetcher(CORPUS) if with_images else None
    days = sorted(p for p in CORPUS.iterdir() if p.is_dir() and p.name.startswith("day"))
    for i, day in enumerate(days):
        clock = _Clock(T0 + timedelta(days=i))
        adapters, normalizer, deduper, _ = discovery_components(
            _corpus_jobs(day, clock), raw_dir=tmp_path / "raw", clock=clock, images=fetcher,
            index_path=tmp_path / "phash-index.json")
        comps = Components(adapters=adapters, normalizer=normalizer, deduper=deduper).with_defaults()
        for name, a in adapters.items():
            for raw in a.fetch():
                norm = normalizer.normalize(raw)
                with engine.begin() as c:
                    spine.ingest(c, asdict(raw), asdict(norm) if norm else None, name, a.version, comps)
    with engine.connect() as c:
        rows = [r[0] for r in c.execute(sa.text("SELECT body FROM mbos.items ORDER BY item_id"))]

    class _Items:
        items = {r["item_id"]: r for r in rows}
    return _Items


def test_corpus_through_spine_f2_zero_missed_zero_false_merges(spine_db, tmp_path):
    labels = json.loads((CORPUS / "labels.json").read_text())
    f2 = check_f2(_run_corpus_through_spine(spine_db, tmp_path, with_images=True), labels)
    assert f2["unlabeled"] == []
    assert (f2["missed_duplicate_rate"], f2["false_merges"]) == (0.0, []), (f2["missed_duplicates"], f2["false_merges"])
    assert (f2["items"], f2["objects"]) == (38, 38)


def test_without_photos_the_spine_shows_the_known_ambiguity(spine_db, tmp_path):
    labels = json.loads((CORPUS / "labels.json").read_text())
    f2 = check_f2(_run_corpus_through_spine(spine_db, tmp_path, with_images=False), labels)
    assert f2["missed_duplicate_rate"] == 0.0
    assert [m["objects"] for m in f2["false_merges"]] == [["obj-ebay-amb-1", "obj-ebay-amb-2"]]


# ---------------------------------------------------------------- the Deduper alone (no DB)
def _existing(source="ebay", lid="A", seller="dealer", first="2026-10-01T12:00:00Z"):
    return {"type": "flip", "category": "trailer", "state": "NORMALIZED", "dedup_key": "k",
            "normalized": {"title": "6x12 enclosed cargo trailer", "price": {"amount": 2000.0, "type": "fixed"},
                           "location": {"city": "Conway", "state": "AR"}, "counterparty": {"role": "seller", "name": seller}},
            "sources": [{"source": source, "source_listing_id": lid, "first_seen_at": first}]}


def _cand(hints, seller="dealer"):
    return NormalizedListing("flip", "trailer", "k", {"title": "6x12 enclosed cargo trailer",
                             "price": {"amount": 1900.0, "type": "fixed"}, "location": {"city": "Conway", "state": "AR"},
                             "counterparty": {"role": "seller", "name": seller}}, match_hints=hints)


def _ctx(source="ebay", lid="B", at="2026-10-04T12:00:00Z"):
    return {"source": source, "source_listing_id": lid, "url": "u", "fetched_at": at, "match_hints": None}


def test_deduper_protocol_and_relist_edges():
    d = SpineDeduper()
    assert isinstance(d, Deduper)
    assert d.is_duplicate(_existing(), _cand({"present_ids": ["B"]}), _ctx())             # original ended → relist
    assert not d.is_duplicate(_existing(), _cand({"present_ids": ["A", "B"]}), _ctx())    # still listed → 2nd unit
    assert not d.is_duplicate(_existing(), _cand({}), _ctx())                             # unknown fetch → never
    assert not d.is_duplicate(_existing(), _cand({"present_ids": ["B"]}, seller="other"), _ctx())
    assert not d.is_duplicate(_existing(), _cand({"present_ids": ["B"]}), _ctx(at="2026-10-20T12:00:00Z"))  # > 14 d
    assert d.is_duplicate(_existing(source="gsa_auctions"), _cand({}), _ctx())            # cross-source rule
    assert not d.is_duplicate(_existing(), _cand({"present_ids": ["B"]}), None) is None   # pre-A-14 call still works
