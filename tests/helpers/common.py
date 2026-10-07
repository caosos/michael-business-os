"""Shared test helpers: fresh databases, fixture variants, waiting on item state."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Iterable

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "sources" / "illustrative.json"


def db_url(base_uri: str, name: str) -> str:
    return base_uri.replace("/postgres?", f"/{name}?")


def create_database(server, prefix: str) -> str:
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    server.psql(f"CREATE DATABASE {name};")
    return db_url(server.get_uri(), name)


def fixture_variant(dest_dir: Path, tag: str, ids: Iterable[str]) -> Path:
    """Copy selected fixture listings with unique listing ids / dedup keys, so each test gets new Items."""
    wanted = set(ids)
    data = json.loads(FIXTURE.read_text())
    out = []
    for rec in data["listings"]:
        if rec["source_listing_id"] not in wanted:
            continue
        rec = json.loads(json.dumps(rec))
        rec["source_listing_id"] = f"{rec['source_listing_id']}-{tag}"
        rec["url"] = f"{rec['url']}?t={tag}"
        rec["record"]["dedup_key"] = f"{rec['record']['dedup_key']}|{tag}"
        out.append(rec)
    p = dest_dir / f"fixture-{tag}.json"
    p.write_text(json.dumps({"listings": out}))
    return p


def item_state(engine: sa.Engine, item_id: str) -> str:
    with engine.connect() as c:
        return c.execute(sa.text("SELECT state FROM mbos.items WHERE item_id = :i"), {"i": item_id}).scalar_one()


def wait_state(engine: sa.Engine, item_id: str, states: str | Iterable[str], timeout: float = 30.0) -> str:
    want = {states} if isinstance(states, str) else set(states)
    deadline = time.monotonic() + timeout
    st = None
    while time.monotonic() < deadline:
        st = item_state(engine, item_id)
        if st in want:
            return st
        time.sleep(0.1)
    raise AssertionError(f"{item_id} stuck in {st}, wanted {sorted(want)}")


def is_lane_d(engine: sa.Engine) -> bool:
    with engine.connect() as c:
        return c.execute(sa.text("SELECT to_regclass('mbos.v_action_request_documents') IS NOT NULL")).scalar_one()


def pending_request(engine: sa.Engine, item_id: str) -> dict:
    """Works on both state backends: reference DDL (`body`) and lane D (document views)."""
    sql = ("SELECT doc FROM mbos.v_action_request_documents WHERE doc->>'item_id' = :i AND doc->>'status' IN "
           "('pending_approval', 'held') ORDER BY doc->>'created_at' DESC LIMIT 1") if is_lane_d(engine) else (
           "SELECT body FROM mbos.action_requests WHERE item_id = :i AND status IN ('pending_approval', 'held') "
           "ORDER BY body->>'created_at' DESC LIMIT 1")
    with engine.connect() as c:
        return c.execute(sa.text(sql), {"i": item_id}).scalar_one()


def scalar(engine: sa.Engine, sql: str, **params):
    with engine.connect() as c:
        return c.execute(sa.text(sql), params).scalar_one()


def receipts_for(engine: sa.Engine, *, item_id: str | None = None, areq: str | None = None, type: str | None = None) -> list[dict]:
    clauses, params = ["true"], {}
    if item_id:
        clauses.append("item_id = :i"); params["i"] = item_id
    if areq:
        clauses.append("action_request_id = :a"); params["a"] = areq
    if type:
        clauses.append("type = :t"); params["t"] = type
    src = ("(SELECT r.seq, r.item_id, r.action_request_id, r.type, d.doc AS body FROM mbos.receipts r "
           "JOIN mbos.v_receipt_documents d USING (receipt_id)) x") if is_lane_d(engine) else "mbos.receipts"
    with engine.connect() as c:
        return [r.body for r in c.execute(sa.text(f"SELECT body FROM {src} WHERE {' AND '.join(clauses)} ORDER BY seq"), params)]


# Michael's explicit step-up confirmation (required by the spine for irreversible / money-like YES).
STEP_UP = {"method": "test_step_up", "step_up": True}
