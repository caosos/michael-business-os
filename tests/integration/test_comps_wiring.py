"""A-39: the real assembly can reach a recommendation. A raw listing WITHOUT inline economics plus Michael's manual comps
(lane B ManualCompsAdapter inbox) reaches SCORED through lane C's research step; with no comps it parks at RESEARCHING with the
exact gap text; `mbos recheck` moves it after a comp is added. Real PG16 (pgserver) + DBOS."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest
import sqlalchemy as sa

pytest.importorskip("mbos_economics.comps_feed")
pytest.importorskip("mbos_discovery.comps")

from dbos import DBOS, SetWorkflowID  # noqa: E402

from mbos import workflows  # noqa: E402
from mbos.adapters.comps import ProductionCompsSource  # noqa: E402
from mbos.adapters.economics import EconomicsResearcher  # noqa: E402
from mbos.config import configure  # noqa: E402
from mbos.reference.fixture_adapter import FixtureSourceAdapter  # noqa: E402
from mbos.runtime import components, item_workflow_id  # noqa: E402
from tests.helpers.common import ROOT, wait_state  # noqa: E402

FIXTURE = ROOT / "fixtures" / "sources" / "no_economics.json"


def _comp(inbox, n: int, price: float, days_ago: int) -> None:
    (inbox / f"comp-{n}.json").write_text(json.dumps({
        "comp_id": f"man-{n}", "category": "trailer", "title": "5x10 utility trailer with ramp gate", "sold_price": price,
        "sold_date": (date.today() - timedelta(days=days_ago)).isoformat(), "where_sold": "facebook marketplace, observed manually",
        "url": f"https://example.invalid/seen/{n}", "condition": "used", "city": "Conway", "state": "AR", "entered_by": "michael"}))


def _discover(rt, tmp_path, tag: str) -> str:
    doc = json.loads(FIXTURE.read_text())
    for l in doc["listings"]:
        l["source_listing_id"] += f"-{tag}"
        l["record"]["dedup_key"] += f"|{tag}"
    f = tmp_path / f"noecon-{tag}.json"
    f.write_text(json.dumps(doc))
    configure(rt.settings)
    components().adapters[tag] = FixtureSourceAdapter(f, name=tag)
    with SetWorkflowID(f"discover:{tag}"):
        results = DBOS.start_workflow(workflows.discover, tag).get_result()
    return next(r["item_id"] for r in results if r["created"])


def test_no_comps_parks_with_gap_then_recheck_scores_after_manual_comps(rt, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    comps_ = components()
    old = comps_.researcher
    comps_.researcher = EconomicsResearcher(ProductionCompsSource(inbox=inbox))
    try:
        tag = "c" + uuid.uuid4().hex[:7]
        item_id = _discover(rt, tmp_path, tag)
        assert wait_state(rt.engine, item_id, {"RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL"}) == "RESEARCHING"
        first = DBOS.retrieve_workflow(item_workflow_id(item_id)).get_result()
        assert first["status"] == "researching" and first["gaps"], first
        assert any("comp" in g.lower() for g in first["gaps"]), first["gaps"]

        for n, (price, ago) in enumerate([(1500, 5), (1650, 12), (1400, 20), (1550, 30)]):
            _comp(inbox, n, price, ago)
        wf = workflows.recheck([item_id])[0]
        out = DBOS.retrieve_workflow(wf).get_result()
        assert out["status"] != "researching", out
        with rt.engine.connect() as c:  # the recheck workflow has returned: scored + recommended (a MAYBE/R13 verdict may route back to RESEARCHING)
            st, doc = c.execute(sa.text("SELECT state, body FROM mbos.items WHERE item_id = :i"), {"i": item_id}).one()
        assert st != "NORMALIZED"
        with rt.engine.connect() as c:
            path = [r.body["after_state"]["state"] for r in c.execute(sa.text(
                "SELECT body FROM mbos.receipts WHERE item_id = :i AND type = 'ITEM_STATE_CHANGED' ORDER BY seq"), {"i": item_id})]
        assert "SCORED" in path, path
        assert doc["scores"]["scorecard"].get("engine_version") and doc["recommendation"]["verdict"], st
        assert doc["economics"], "lane C filled the economics from comps"
    finally:
        comps_.researcher = old


def test_source_describes_itself_and_merges_store_and_inbox(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _comp(inbox, 1, 1500, 3)
    src = ProductionCompsSource(tmp_path / "comps.json", inbox)
    assert "manual inbox" in src.describe() and ProductionCompsSource().describe() == "none"
    item = {"type": "flip", "category": "trailer", "created_at": "2026-10-08T12:00:00Z",
            "normalized": {"title": "5x10 utility trailer with ramp gate"}, "sources": []}
    comps, prov = src(item)
    assert [c["source_comp_id"] for c in comps] == ["man-1"] and prov and prov[0]["actor_type"] == "human"


def test_assembly_report_names_the_comps_source_or_says_stand_in(monkeypatch, tmp_path):
    from mbos.config import Settings
    from mbos.production import build_components

    s = Settings(database_url="postgresql://x/y", system_database_url="postgresql://x/z")
    monkeypatch.delenv("MBOS_COMPS_STORE", raising=False)
    monkeypatch.delenv("MBOS_COMPS_INBOX", raising=False)
    comps, report = build_components(s)
    row = next(r for r in report if r["component"] == "research (comps)")
    assert comps.researcher is None and row["kind"] == "STAND-IN" and row["detail"].startswith("none")
    monkeypatch.setenv("MBOS_COMPS_INBOX", str(tmp_path))
    comps, report = build_components(s)
    row = next(r for r in report if r["component"] == "research (comps)")
    assert type(comps.researcher).__name__ == "EconomicsResearcher" and row["kind"] == "REAL" and str(tmp_path) in row["detail"]
