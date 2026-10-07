"""D-08 / acceptance D3: pgvector is a rebuildable index — drop, rebuild, identical query results."""

import psycopg
import pytest
from psycopg import errors

from mbos_state import vector_index as vi
from conftest import AGENT, key, tool_prov

EMB = vi.HashEmbedder()
CATALOGUE = [
    ("flip", "trailer", "6x12 utility trailer, new tires, clean title"),
    ("flip", "trailer", "5x8 enclosed cargo trailer needs wiring"),
    ("flip", "mower", "zero-turn riding mower, deck needs blades"),
    ("flip", "mower", "push mower runs rough, carb cleaning"),
    ("flip", "generator", "7500W portable generator, won't start"),
    ("flip", "welder", "MIG welder 140A with gas regulator"),
    ("flip", "compressor", "60 gallon air compressor, pressure switch bad"),
    ("service", "drywall_repair", "patch two holes in living room drywall"),
    ("service", "drywall_repair", "water damaged ceiling drywall replace and texture"),
    ("service", "smart_home_install", "install video doorbell and smart thermostat"),
    ("service", "assembly", "assemble IKEA wardrobe and bed frame"),
    ("service", "equipment_repair", "repair pressure washer pump leak"),
]
QUERIES = ["utility trailer", "riding mower blades", "drywall hole patch", "generator repair", "smart doorbell"]


@pytest.fixture
def populated(db):
    s = db.store()
    pid = tool_prov(s)
    for i, (lane, cat, title) in enumerate(CATALOGUE):
        s.create_item({"type": lane, "category": cat, "dedup_key": f"blk-{i}", "sources": [],
                       "normalized": {"title": title}}, AGENT, "seed", [pid], key())
    return db


def _results(conn, exact):
    return {q: vi.search(conn, EMB, q, k=5, exact=exact) for q in QUERIES}


def _hnsw_results(conn):
    """Force the HNSW path (tiny tables would otherwise seq-scan) and prove it with EXPLAIN."""
    out = {}
    with conn.transaction():
        conn.execute("SET LOCAL enable_seqscan = off")
        conn.execute("SET LOCAL hnsw.ef_search = 200")
        for q in QUERIES:
            sql = ("SELECT item_id, round((embedding OPERATOR(mbos_ext.<=>) %(v)s::mbos_ext.vector)::numeric, 9) "
                   "FROM mbos.item_embeddings ORDER BY embedding OPERATOR(mbos_ext.<=>) %(v)s::mbos_ext.vector LIMIT 12")
            v = {"v": vi._vec(EMB.embed(q))}
            plan = "\n".join(r[0] for r in conn.execute("EXPLAIN " + sql, v))
            assert "item_embeddings_hnsw" in plan, plan
            # k = whole table so no LIMIT boundary splits a tie; ties (orthogonal items, distance 1.0) have no
            # defined HNSW order, so compare as (distance, item_id)-sorted lists
            out[q] = sorted((float(r[1]), r[0]) for r in conn.execute(sql, v))
    return out


def test_d3_drop_rebuild_identical_results(populated):
    w = populated.connect("agent_write")
    assert vi.refresh(w, EMB) == len(CATALOGUE)
    assert vi.verify(w, EMB) == []
    before_idx, before_exact = _results(w, False), _results(w, True)
    assert before_idx == before_exact
    before_hnsw = _hnsw_results(w)
    exact_all = {q: sorted((d, i) for i, d in vi.search(w, EMB, q, k=12, exact=True)) for q in QUERIES}
    assert before_hnsw == exact_all                                          # HNSW agrees with ground truth
    assert before_idx["utility trailer"][0][0] is not None
    rows_before = w.execute("SELECT item_id, content_hash, embedding::text FROM mbos.item_embeddings ORDER BY 1").fetchall()

    owner = populated.connect("owner")
    owner.execute("DROP INDEX mbos.item_embeddings_hnsw")
    owner.execute("DELETE FROM mbos.item_embeddings")                     # the index is gone entirely
    assert vi.search(w, EMB, "utility trailer") == []
    assert vi.rebuild(owner, EMB) == len(CATALOGUE)

    rows_after = w.execute("SELECT item_id, content_hash, embedding::text FROM mbos.item_embeddings ORDER BY 1").fetchall()
    assert rows_after == rows_before                                         # byte-identical projection
    assert _results(w, False) == before_idx and _results(w, True) == before_exact
    assert _hnsw_results(w) == before_hnsw                                   # rebuilt HNSW: identical results
    assert w.execute("SELECT count(*) FROM pg_indexes WHERE indexname='item_embeddings_hnsw'").fetchone()[0] == 1


def test_similarity_is_meaningful(populated):
    w = populated.connect("agent_write")
    vi.refresh(w, EMB)
    titles = dict(w.execute("SELECT item_id, doc->'normalized'->>'title' FROM mbos.items").fetchall())
    top = titles[vi.search(w, EMB, "6x12 utility trailer new tires", k=1)[0][0]]
    assert top.startswith("6x12 utility trailer")


def test_drift_detected_and_refresh_is_incremental(populated):
    w = populated.connect("agent_write")
    vi.refresh(w, EMB)
    s = populated.store("agent_write")
    item_id = w.execute("SELECT item_id FROM mbos.items ORDER BY item_id LIMIT 1").fetchone()[0]
    pid = tool_prov(s)
    s.update_item_doc(item_id, {"normalized": {"title": "changed title"}}, "ITEM_STATE_CHANGED", AGENT, "edit", [pid], key())
    s.create_item({"type": "flip", "category": "tool", "dedup_key": "new", "sources": [],
                   "normalized": {"title": "impact driver"}}, AGENT, "new", [pid], key())
    problems = vi.verify(w, EMB)
    assert sorted(p.split()[0] for p in problems) == ["missing", "stale"]
    assert vi.refresh(w, EMB) == 2                                            # only the two changed rows
    assert vi.verify(w, EMB) == []


def test_index_privileges(populated):
    w = populated.connect("agent_write")
    vi.refresh(w, EMB)
    with pytest.raises(errors.InsufficientPrivilege):
        w.execute("DELETE FROM mbos.item_embeddings")                       # drop/rebuild is owner maintenance
    with pytest.raises(errors.InsufficientPrivilege):
        populated.connect("reader").execute(
            "INSERT INTO mbos.item_embeddings SELECT item_id, 'm','1', content_hash, embedding FROM mbos.item_embeddings")
    assert vi.search(populated.connect("reader"), EMB, "mower", k=2)        # readers can query


def test_embedding_rows_are_not_truth(populated):
    """Rebuilding never touches the ledger: chain head and items are unchanged."""
    w = populated.connect("agent_write")
    head = w.execute("SELECT row_hash FROM mbos.chain_head()").fetchone()[0]
    items = w.execute("SELECT count(*), max(version) FROM mbos.items").fetchone()
    vi.rebuild(populated.connect("owner"), EMB)
    assert w.execute("SELECT row_hash FROM mbos.chain_head()").fetchone()[0] == head
    assert w.execute("SELECT count(*), max(version) FROM mbos.items").fetchone() == items
