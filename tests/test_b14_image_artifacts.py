"""B-14: lane B photos into the spine's artifact store; `normalized.images` round-trips by sha256 on the spine path."""

from __future__ import annotations

import hashlib
import json
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

import sqlalchemy as sa  # noqa: E402

from conftest import FIX  # noqa: E402
from mbos_discovery.acceptance import T0, _Clock, _corpus_jobs, check_f2, image_fetcher  # noqa: E402
from mbos_discovery.artifacts import (LaneDArtifactSink, ReferenceSpineArtifactSink, sniff_media_type,  # noqa: E402
                                      upload)
from mbos_discovery.images import phash  # noqa: E402
from mbos_discovery.spine import PhashIndex, discovery_components  # noqa: E402

CORPUS = FIX / "corpus7d"
PNG = (CORPUS / "images" / "500000000001.png").read_bytes()


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    import pgserver
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pg14")), cleanup_mode="stop")
    yield server
    server.cleanup()


@pytest.fixture
def spine_db(pg):
    from mbos.config import Settings, configure
    from mbos.db.engine import engine_for
    from mbos.db.migrate import migrate
    name = f"b14_{uuid.uuid4().hex[:10]}"
    pg.psql(f"CREATE DATABASE {name};")
    url = pg.get_uri().replace("/postgres?", f"/{name}?")
    configure(Settings(database_url=url, system_database_url=url))
    engine = engine_for(url)
    migrate(engine)
    yield engine
    engine.dispose()


def _through_spine(engine, tmp_path, sink):
    from mbos import spine
    from mbos.runtime import Components
    fetcher = image_fetcher(CORPUS)
    for i, day in enumerate(sorted(p for p in CORPUS.iterdir() if p.is_dir() and p.name.startswith("day"))):
        clock = _Clock(T0 + timedelta(days=i))
        adapters, normalizer, deduper, _ = discovery_components(
            _corpus_jobs(day, clock), raw_dir=tmp_path / "raw", clock=clock, images=fetcher,
            index_path=tmp_path / "idx.json", artifact_sink=sink)
        comps = Components(adapters=adapters, normalizer=normalizer, deduper=deduper).with_defaults()
        for name, a in adapters.items():
            for raw in a.fetch():
                norm = normalizer.normalize(raw)
                with engine.begin() as c:
                    spine.ingest(c, asdict(raw), asdict(norm) if norm else None, name, a.version, comps)
    with engine.connect() as c:
        return [r[0] for r in c.execute(sa.text("SELECT body FROM mbos.items ORDER BY item_id"))]


def test_images_round_trip_by_sha256_on_the_spine_path(spine_db, tmp_path):
    items = _through_spine(spine_db, tmp_path, ReferenceSpineArtifactSink(spine_db))
    index = PhashIndex.load(tmp_path / "idx.json")
    ebay = [i for i in items if any(s["source"] == "ebay" for s in i["sources"])]
    assert ebay and all(i["normalized"].get("images") for i in ebay)
    with spine_db.connect() as c:
        for item in ebay:
            for ref in item["normalized"]["images"]:
                content, mt = c.execute(sa.text("SELECT content, media_type FROM mbos.artifacts WHERE sha256 = :h"),
                                        {"h": ref}).one()
                content = bytes(content)
                assert "sha256:" + hashlib.sha256(content).hexdigest() == ref and mt == "image/png"
                assert phash(content) in index.hashes(item["sources"])       # same photo the Deduper judged
    labels = json.loads((CORPUS / "labels.json").read_text())

    class _Store:
        pass
    store = _Store()
    store.items = {i["item_id"]: i for i in items}
    f2 = check_f2(store, labels)
    assert (f2["missed_duplicate_rate"], f2["false_merges"]) == (0.0, [])     # B-13 result unchanged


def test_without_a_sink_nothing_is_referenced(spine_db, tmp_path):
    items = _through_spine(spine_db, tmp_path, None)
    assert not any(i["normalized"].get("images") for i in items)              # never a ref the spine can't resolve


def test_upload_is_fail_safe():
    class Liar:
        def put(self, data, mt):
            return "sha256:" + "0" * 64

    class Broken:
        def put(self, data, mt):
            raise PermissionError("no rights")

    assert upload(Liar(), PNG) is None and upload(Broken(), PNG) is None and upload(None, PNG) is None
    assert upload(Liar(), b"not an image") is None
    assert sniff_media_type(PNG) == "image/png" and sniff_media_type(b"\xff\xd8\xff\xe0") == "image/jpeg"


# ---------------------------------------------------------------- lane D canonical store (Agent 04 @ 14bd690)
@pytest.fixture(scope="module")
def cluster():
    from lane_de import Cluster
    c = Cluster()
    yield c
    c.stop()


def _lane_d_engine(cluster, role_login, dbname):
    return sa.create_engine(f"postgresql+psycopg://{role_login}@/{dbname}?host={cluster.sock}&port={cluster.port}")


def test_lane_d_put_artifact_round_trip_and_permissions(cluster):
    import psycopg
    from lane_de import LOGIN, TEMPLATE
    db = f"b14d_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(f"{cluster.base} dbname=postgres user=postgres", autocommit=True) as c:
        c.execute(f"CREATE DATABASE {db} TEMPLATE {TEMPLATE} OWNER mbos_owner")
    writer = _lane_d_engine(cluster, LOGIN["agent_write"], db)
    reader = _lane_d_engine(cluster, LOGIN["reader"], db)
    try:
        ref = upload(LaneDArtifactSink(writer), PNG)
        assert ref == "sha256:" + hashlib.sha256(PNG).hexdigest()
        assert upload(LaneDArtifactSink(writer), PNG) == ref                   # idempotent
        with reader.connect() as c:
            content, mt = c.execute(sa.text("SELECT content, media_type FROM mbos.artifacts WHERE sha256 = :h"),
                                    {"h": ref}).one()
        assert bytes(content) == PNG and mt == "image/png"
        other = (CORPUS / "images" / "500000000002.png").read_bytes()
        assert upload(LaneDArtifactSink(reader), other) is None                # read-only login: refused, not referenced
    finally:
        writer.dispose()
        reader.dispose()
