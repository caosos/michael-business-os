"""F-25: /wanted on the spine campaigns (migration 0019) through lane D's REAL Operator UI login (`mbos_operator_ui`). Create, pause,
resume and cancel are receipted (entity_type campaign, actor human:<id>); the chain verifies; ASSISTED_DEAL / AUTOPILOT are refused
and store nothing; the 5x8 example still matches (02's matcher) over the stored document."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.lane_d.test_my_numbers_f22 import post, ui_least, ui_role  # noqa: F401
from tests.lane_d.test_ui_on_lane_d import req

pytestmark = pytest.mark.usefixtures("rtd")
TRAILER = {"title": "5x8 utility trailer within 40 miles, max $600", "category": "trailer", "keywords": "5x8, utility",
           "max_price_usd": "600", "radius_miles": "40", "nice_to_have": "title", "level": "RECOMMEND"}
ITEMS = json.loads((Path(__file__).resolve().parents[1] / "fixtures/campaign_items.json").read_text())["items"]


def rows(rtd, cid=None):
    with rtd.engine.connect() as c:
        q = "SELECT revision, status, created_by FROM mbos.campaigns" + (" WHERE campaign_id = :c" if cid else "") + " ORDER BY campaign_id, revision"
        return c.execute(sa.text(q), {"c": cid} if cid else {}).all()


def receipts(rtd, cid):
    with rtd.engine.connect() as c:
        return c.execute(sa.text("SELECT actor, effect FROM mbos.receipts WHERE entity_type = 'campaign' AND entity_id = :c ORDER BY seq"),
                         {"c": cid}).all()


def test_create_pause_resume_cancel_are_receipted_and_the_chain_verifies(rtd, ui_least):
    ui = ui_least
    assert ui._spine_campaigns()
    status, loc, _ = post(ui, "/wanted/create", **TRAILER)
    assert status == 303 and "Receipt" in loc
    cid = loc.split("(")[1].split(")")[0] if "(" in loc else loc.split("%28")[1].split("%29")[0]
    rec = next(r for r in ui.campaign_records() if r["doc"]["campaign_id"] == cid)
    from mbos import campaign
    campaign.validate(rec["doc"])
    for act in ("pause", "resume", "cancel"):
        assert post(ui, f"/wanted/{cid}/{act}")[0] == 303
    assert [(r[0], r[1]) for r in rows(rtd, cid)] == [(1, "ACTIVE"), (2, "PAUSED"), (3, "ACTIVE"), (4, "CANCELLED")]
    rc = receipts(rtd, cid)
    assert len(rc) == 4 and all(a.get("type") == "human" and a.get("id") for a, _ in rc)
    assert "CANCELLED" in req(ui, "GET", "/wanted")[2]
    assert ui.store.verify_chain()["ok"] is True
    assert post(ui, f"/wanted/{cid}/resume")[2].count("cannot resume") == 1


@pytest.mark.parametrize("level", ["ASSISTED_DEAL", "BOUNDED_AUTOPILOT"])
def test_refused_levels_store_nothing(rtd, ui_least, level):
    before = len(rows(rtd))
    status, _, body = post(ui_least, "/wanted/create", **{**TRAILER, "level": level})
    assert status == 200 and "refused" in body and len(rows(rtd)) == before


def test_the_5x8_example_still_matches_over_the_stored_document(rtd, ui_least):
    post(ui_least, "/wanted/create", **TRAILER)
    docs = [r["doc"] for r in ui_least.campaign_records() if r["doc"]["title"] == TRAILER["title"] and r["doc"]["status"] == "ACTIVE"]
    assert docs
    from mbos_discovery.campaigns import match_campaign
    from mbos.clock import utcnow
    got = {m["item_id"] for m in match_campaign(docs[0], ITEMS, utcnow())["matches"]}
    assert got == {"itm_%026d" % n for n in (1, 2, 4, 9, 15, 16)}
