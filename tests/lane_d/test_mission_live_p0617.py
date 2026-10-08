"""P-06-17: /mission on lane D is produced from live Items by 03's mission_feed (+ capital_position_document), file as fallback."""

from __future__ import annotations

import http.client
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from operator_ui import mission_view as mv

pytestmark = pytest.mark.lane_d


def get(ui, path):
    c = http.client.HTTPConnection("127.0.0.1", ui.port, timeout=20)
    c.request("GET", path, headers={"Host": f"127.0.0.1:{ui.port}"})
    r = c.getresponse()
    return r.status, r.read().decode()


def _stub_scorecards(ui):
    from mbos_economics import mission_feed

    """FINDING for 03: Items scored by the UI's test scorer carry a scorecard WITHOUT the decision `branches`; mission_feed (0.13.1)
    raises KeyError on them instead of skipping/flagging them. Until that is fixed the page falls back to the file and says why."""
    with ui.store.engine.connect() as c:
        docs = [r[0] for r in c.execute(sa.text("SELECT doc FROM mbos.v_item_documents WHERE doc ? 'scores'"))]
    return any(d["scores"].get("scorecard") and d.get("state") not in mission_feed.LIVE_EXCLUDED for d in docs)


def test_live_plan_on_lane_d_is_valid_and_never_invented(ui_d):
    from mbos import mission

    out = mv.load_live(ui_d.store, datetime.now(timezone.utc))
    if _stub_scorecards(ui_d):
        if out["source"].startswith("lane D"):  # lane C 0.14 skips scorecards without branches (P-06-18): the live plan is valid
            assert out["kind"] == "plan" and out["errors"] == []
        else:
            assert "file fallback (live producer failed: KeyError)" == out["source"] and out["kind"] == "none"
        return
    assert out["source"].startswith("lane D") and out["kind"] == "plan" and out["errors"] == []
    mission.validate_plan(out["doc"])
    if not out["doc"]["legs"]:  # no scored live Items: no invented opportunity, nothing to spend
        assert out["doc"]["recommendation"] in ("DO_NOT_SPEND", "UNKNOWN")


def test_mission_page_renders_live_source(ui_d):
    st, body = get(ui_d, "/mission")
    assert st == 200 and ("Source: lane D (live Items)" in body or "Source: file fallback (live producer failed" in body)


def test_live_failure_falls_back_to_the_file(ui_d, tmp_path):
    class Broken:
        lane = "lane_d"
        engine = None  # .connect() raises AttributeError -> fallback
    out = mv.load_live(Broken(), datetime.now(timezone.utc), str(tmp_path / "missing.json"))
    assert out["kind"] == "none" and "file fallback" in out["source"] and "AttributeError" in out["source"]
