"""Drive the whole spine with plain transactions (no DBOS) to populate every ledger table."""

from __future__ import annotations

from dataclasses import asdict

import sqlalchemy as sa

from mbos import spine
from mbos.reference.fixture_adapter import FixtureSourceAdapter
from mbos.runtime import Components
from tests.helpers.common import FIXTURE


def seed_flow(engine: sa.Engine, listing: str = "FIX-TRAILER-1", *, act: bool = True, outcome: bool = True) -> dict:
    comps = Components().with_defaults()
    raw = next(r for r in FixtureSourceAdapter(FIXTURE, name="fixture").fetch() if r.source_listing_id == listing)
    norm = comps.normalizer.normalize(raw)
    with engine.begin() as c:
        item_id = spine.ingest(c, asdict(raw), asdict(norm), "fixture", "0.1.0")["item_id"]
    with engine.begin() as c:
        item = spine.read_item(c, item_id)
    with engine.begin() as c:
        spine.record_score(c, item_id, asdict(comps.scorer.score(item)))
    with engine.begin() as c:
        areq_id = spine.route_recommendation(c, item_id, comps)["action_request_id"]
    out = {"item_id": item_id, "action_request_id": areq_id, "components": comps}
    if not act or areq_id is None:
        return out
    with engine.begin() as c:
        h = c.execute(sa.text("SELECT payload_hash FROM mbos.action_requests WHERE action_request_id = :a"),
                      {"a": areq_id}).scalar_one()
        approval = spine.decide(c, areq_id, "YES", h, comps)["approval"]
    with engine.begin() as c:
        spine.begin_act(c, item_id, areq_id, approval)
    guard = asdict(comps.gateway.execute(engine, areq_id, approval["approval_id"]))
    with engine.begin() as c:
        spine.finish_act(c, item_id, areq_id, approval, guard)
    if outcome:
        with engine.begin() as c:
            spine.record_outcome(c, item_id, "flip_acquired", realized={"total_cost": 825},
                                 predicted_vs_actual=[{"field": "acquisition.expected_buy_price", "predicted": 800, "actual": 800}])
    out.update(approval_id=approval["approval_id"], guard=guard)
    return out
