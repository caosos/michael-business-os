"""D-16 / ADR-0011: card enrichment on lane D — UI/reader roles read enrichment, lane agents write research[],
concurrent enrichments never lose an entry, and v_item_card_inputs gives the UI one row per block."""

import json
import threading

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import AGENT, key, make_item, tool_prov

LANE = {"type": "agent", "id": "agent-03-economics"}


def enrich(conn, item_id, block, data, pid, basis="INFERENCE", idem=None):
    """What spine_d.record_enrichment does, on lane D's API: artifact first, then an atomic research[] append."""
    sha = conn.execute("SELECT mbos.put_artifact(%s, 'application/json')",
                       (json.dumps(data, sort_keys=True, separators=(",", ":")).encode(),)).fetchone()[0]
    entry = {"finding": f"card enrichment: {block}", "field": f"card.{block}", "basis": basis,
             "source_uri": f"artifact:{sha}", "provenance_id": pid}
    conn.execute("SELECT mbos.append_item_research(%s, %s, %s, %s, %s, %s)",
                 (item_id, Jsonb([entry]), Jsonb(LANE), f"card enrichment {block}", [pid], idem or key("enr")))
    return sha


@pytest.fixture
def card(db):
    s = db.store()
    item_id, pid = make_item(s, "RESEARCHING")
    return db, item_id, pid


def test_ui_roles_read_enrichment_and_raw_artifact_content(card):
    db, item_id, pid = card
    lane = db.connect("agent_write")
    sha = enrich(lane, item_id, "comps", {"sold": [{"price": 850.0}, {"price": 910.0}], "n": 2}, pid)
    for role in ("reader", "approver"):                       # Operator UI backend and read-only roles
        c = db.connect(role)
        row = c.execute("SELECT block, basis, artifact_sha256, data, artifact_missing FROM mbos.v_item_card_inputs "
                        "WHERE item_id=%s", (item_id,)).fetchone()
        assert row == ("comps", "INFERENCE", sha, {"sold": [{"price": 850.0}, {"price": 910.0}], "n": 2}, False), role
        raw = c.execute("SELECT content FROM mbos.artifacts WHERE sha256=%s", (sha,)).fetchone()[0]   # direct read too
        assert json.loads(bytes(raw))["n"] == 2
    assert db.connect("reader").execute("SELECT count(*) FROM mbos.v_item_card_inputs").fetchone()[0] == 1


def test_lane_agents_may_patch_research_others_may_not(card):
    db, item_id, pid = card
    lane = db.connect("agent_write")
    lane.execute("SELECT mbos.update_item_doc(%s, %s, 'ITEM_STATE_CHANGED', %s, 'plain research patch', %s, %s)",
                 (item_id, Jsonb({"research": [{"finding": "x", "field": "card.notes", "basis": "FACT"}]}),
                  Jsonb(LANE), [pid], key()))
    for role in ("reader", "approver"):
        with pytest.raises(errors.InsufficientPrivilege):
            db.connect(role).execute("SELECT mbos.update_item_doc(%s, %s, 'ITEM_STATE_CHANGED', %s, 'x', %s, %s)",
                                     (item_id, Jsonb({"research": []}), Jsonb(LANE), [pid], key()))
        with pytest.raises(errors.InsufficientPrivilege):
            db.connect(role).execute("SELECT mbos.append_item_research(%s, %s, %s, 'x', %s, %s)",
                                     (item_id, Jsonb([{"field": "card.x"}]), Jsonb(LANE), [pid], key()))
    with pytest.raises(errors.InsufficientPrivilege):            # the UI cannot create artifacts either
        db.connect("approver").execute("SELECT mbos.put_artifact(%s, 'application/json')", (b"{}",))


def test_plain_read_modify_write_loses_entries_but_append_does_not(card):
    db, item_id, pid = card
    barrier = threading.Barrier(2)

    def rmw(name):                       # what a lane does if it patches research[] itself
        c = db.connect("agent_write", autocommit=False)
        with c.transaction():
            cur = c.execute("SELECT doc->'research' FROM mbos.items WHERE item_id=%s", (item_id,)).fetchone()[0] or []
            barrier.wait(timeout=10)
            c.execute("SELECT mbos.update_item_doc(%s,%s,'ITEM_STATE_CHANGED',%s,'rmw',%s,%s)",
                      (item_id, Jsonb({"research": cur + [{"field": f"card.{name}"}]}), Jsonb(LANE), [pid], key()))

    ts = [threading.Thread(target=rmw, args=(n,)) for n in ("a", "b")]
    [t.start() for t in ts]; [t.join() for t in ts]
    lost = db.connect().execute("SELECT jsonb_array_length(doc->'research') FROM mbos.items WHERE item_id=%s",
                                (item_id,)).fetchone()[0]
    assert lost == 1                                              # documents the hazard: one of two entries lost

    item2, pid2 = make_item(db.store(), "RESEARCHING")
    blocks = [f"b{i}" for i in range(12)]

    def appender(b):
        enrich(db.connect("agent_write"), item2, b, {"block": b}, pid2)

    ts = [threading.Thread(target=appender, args=(b,)) for b in blocks]
    [t.start() for t in ts]; [t.join() for t in ts]
    got = sorted(r[0] for r in db.connect("reader").execute(
        "SELECT block FROM mbos.v_item_card_inputs WHERE item_id=%s", (item2,)))
    assert got == sorted(blocks)                                  # all 12 concurrent enrichments survive
    assert db.connect().execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]


def test_latest_entry_per_block_wins_and_blocks_are_independent(card):
    db, item_id, pid = card
    lane = db.connect("agent_write")
    enrich(lane, item_id, "comps", {"v": 1}, pid)
    enrich(lane, item_id, "photos", {"urls": ["a"]}, pid)
    enrich(lane, item_id, "comps", {"v": 2}, pid)                 # a refresh supersedes the first comps block
    rows = {b: (d, idx) for b, d, idx in db.connect("reader").execute(
        "SELECT block, data, research_index FROM mbos.v_item_card_inputs WHERE item_id=%s", (item_id,))}
    assert rows["comps"] == ({"v": 2}, 3) and rows["photos"] == ({"urls": ["a"]}, 2)
    n = db.connect().execute("SELECT jsonb_array_length(doc->'research') FROM mbos.items WHERE item_id=%s", (item_id,))
    assert n.fetchone()[0] == 3                                   # history is kept; the view shows the latest


def test_view_survives_malformed_and_missing_artifacts(card):
    db, item_id, pid = card
    lane = db.connect("agent_write")
    bad = lane.execute("SELECT mbos.put_artifact(%s, 'application/json')", (b"{not json",)).fetchone()[0]
    entries = [
        {"field": "card.broken", "finding": "x", "basis": "FACT", "source_uri": f"artifact:{bad}", "provenance_id": pid},
        {"field": "card.ghost", "finding": "x", "basis": "FACT", "provenance_id": pid,
         "source_uri": "artifact:sha256:" + "0" * 64},
        {"field": "card.nouri", "finding": "x", "basis": "FACT", "provenance_id": pid},
    ]
    lane.execute("SELECT mbos.append_item_research(%s, %s, %s, 'x', %s, %s)", (item_id, Jsonb(entries), Jsonb(LANE), [pid], key()))
    rows = {b: (d, m) for b, d, m in db.connect("reader").execute(
        "SELECT block, data, artifact_missing FROM mbos.v_item_card_inputs WHERE item_id=%s", (item_id,))}
    assert rows == {"broken": (None, False), "ghost": (None, True), "nouri": (None, True)}


def test_append_is_replay_safe_and_validated(card):
    db, item_id, pid = card
    lane = db.connect("agent_write")
    k = key("replay")
    args = (item_id, Jsonb([{"field": "card.x", "finding": "x"}]), Jsonb(LANE), "x", [pid], k)
    r1 = lane.execute("SELECT mbos.append_item_research(%s,%s,%s,%s,%s,%s)", args).fetchone()[0]
    r2 = lane.execute("SELECT mbos.append_item_research(%s,%s,%s,%s,%s,%s)", args).fetchone()[0]
    assert r1 == r2
    assert lane.execute("SELECT jsonb_array_length(doc->'research') FROM mbos.items WHERE item_id=%s", (item_id,)).fetchone()[0] == 1
    for bad in (Jsonb([]), Jsonb({"field": "x"})):
        with pytest.raises(psycopg.Error) as ei:
            lane.execute("SELECT mbos.append_item_research(%s,%s,%s,'x',%s,%s)", (item_id, bad, Jsonb(LANE), [pid], key()))
        assert ei.value.sqlstate == "MB004"
    with pytest.raises(psycopg.Error) as ei:
        lane.execute("SELECT mbos.append_item_research(%s,%s,%s,'x',%s,%s)",
                     ("itm_" + "0" * 26, Jsonb([{"field": "card.x"}]), Jsonb(LANE), [pid], key()))
    assert ei.value.sqlstate == "MB404"
