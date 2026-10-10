"""F-49: demo/training items on no non-demo page (every nav route walked); ZIP/city located from a local gazetteer or said plainly."""

from __future__ import annotations

import json
import pytest

from operator_ui import gazetteer, landing_fix
from operator_ui import market_search as ms
from operator_ui.server import NAV
from tests.test_f29_ui import PLAN, leg
from tests.test_landing_f48 import Store
from tests.test_market_f47 import cache, get, ui  # noqa: F401  (fixtures)
from tests.test_operator_ui import req

@pytest.fixture(autouse=True)
def _strict(monkeypatch):
    monkeypatch.delenv("MBOS_UI_FIXTURE_ITEMS", raising=False)


TRAIN = {"item_id": "TRAIN-TV-1", "dedup_key": "train-tv", "type": "flip", "normalized": {"title": "55 inch LED TV"}, "sources": [{"url": "https://example.invalid/tv"}]}
BAD = ("TRAIN-", "example.invalid", "55 inch", "LED TV")


class DemoStore:
    """Wraps the F-47 stub, adding a demo item to every reader the pages use."""
    def __init__(self, inner):
        self._i = inner
        self.lane = "reference"

    def __getattr__(self, n):
        return getattr(self._i, n)

    def item(self, iid):
        return TRAIN if iid == "TRAIN-TV-1" else None

    def items_in_states(self, states):
        return [TRAIN] + list(self._i.items_in_states(states))

    def held(self):
        return [{"item": TRAIN, "action_request": {"action_request_id": "areq_1", "capability": "x"}, "held_at": "2026-10-09T00:00:00Z", "hold": {}}]

    def outcomes(self, item_id=None, limit=100):
        return [{"outcome_id": "o1", "item_id": "TRAIN-TV-1", "kind": "sold", "observed_at": "2026-10-08T12:00:00Z", "realized": {"net_profit": 50}}]

    def receipts(self, item_id=None, areq_id=None, limit=500):
        return [{"seq": 1, "item_id": "TRAIN-TV-1", "ts": "t", "type": "x", "actor": {"id": "a"}, "intent": "55 inch LED TV", "provenance_ids": [], "row_hash": "sha256:" + "0" * 64}]

    def action_requests(self, *a, **k):
        return []

    def my_numbers(self):
        return {"mission": None, "ledger": None, "available": False}

    def operator_notes(self, **k):
        return []

    def parked(self, *a, **k):
        return []

    def verify_chain(self):
        return {"ok": True, "checked": 1}

    def verify_chain_independent(self):
        return True, "ok"


def test_every_nav_route_has_no_demo_text(ui, tmp_path):
    import copy
    doc = copy.deepcopy(PLAN)
    doc["legs"] = [leg(item_id="TRAIN-TV-1", title="55 inch LED TV", verdict="YES", waiting_on=[])]
    mf = tmp_path / "mission.json"
    mf.write_text(json.dumps(doc))
    ui.mission_file = str(mf)
    ui.store = DemoStore(ui.store)
    seen = 0
    for href, _title, _k in NAV:
        s, _loc, h = req(ui, "GET", href)
        assert s == 200, (href, s)
        seen += 1
        for bad in BAD:
            assert bad not in h, (href, bad)
    assert seen == len(NAV)


def test_live_store_hides_demo_but_keeps_real():
    class S(DemoStore):
        def __init__(self):
            pass
        def item(self, iid):
            return TRAIN if iid.startswith("TRAIN") else {"item_id": iid, "sources": [{"url": "https://www.gsaauctions.gov/a"}]}
        def items_in_states(self, states):
            return [TRAIN, self.item("itm_real")]
        def held(self):
            return []
        def outcomes(self, item_id=None, limit=100):
            return [{"item_id": "TRAIN-TV-1"}, {"item_id": "itm_real"}]
        def receipts(self, *a, **k):
            return [{"item_id": "TRAIN-TV-1"}, {"item_id": None}, {"item_id": "itm_real"}]
    ls = landing_fix.LiveStore(S())
    assert [i["item_id"] for i in ls.items_in_states(())] == ["itm_real"]
    assert [o["item_id"] for o in ls.outcomes()] == ["itm_real"]
    assert [r["item_id"] for r in ls.receipts()] == [None, "itm_real"]


def test_zip_72032_is_located_and_unknown_zip_is_said_plainly(ui):
    assert gazetteer.locate("72032") == (35.0887, -92.4421)
    assert gazetteer.locate("Conway, AR") == (35.0887, -92.4421) and gazetteer.locate("conway arkansas")
    assert gazetteer.locate("00000") is None and gazetteer.locate("Nowhereville, ZZ") is None
    assert ms._origin("72032") == (35.0887, -92.4421)
    h = get(ui, go=1, keywords="trailer", base="72032", radius="25")
    assert "not located" not in h
    h = get(ui, go=1, keywords="trailer", base="00000", radius="25")
    assert "accepted but not located" in h and "No network lookup" in h


def test_gazetteer_file_override(tmp_path, monkeypatch):
    f = tmp_path / "g.csv"
    f.write_text("zip,city,state,lat,lng\n99999,Testville,ZZ,1.5,2.5\n")
    monkeypatch.setenv("MBOS_GAZETTEER_FILE", str(f))
    assert gazetteer.locate("99999") == (1.5, 2.5) and gazetteer.locate("Testville, ZZ") == (1.5, 2.5)
    assert gazetteer.locate("72032") is None
