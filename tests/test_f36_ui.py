"""F-36: G-22 repros F-121..F-125 (pure renderers; no DB)."""
import copy
import json

from operator_ui import comps_view as cv
from operator_ui import mission_view as mv
from tests.test_f29_ui import PLAN, leg


def _plan(**kw):
    doc = copy.deepcopy(PLAN)
    doc["recommendation"] = "DEPLOY"
    doc["legs"] = [leg(title="TV flip", item_id="itm_tv", verdict="YES", waiting_on=[], **kw)]
    return doc


def _hdr(doc, states):
    return mv.today_header({"kind": "plan", "doc": doc, "errors": []}, None, states)


def test_f121_next_move_after_hold_and_after_execution():
    doc = _plan()
    assert "ready for your YES" in _hdr(doc, {"itm_tv": "AWAITING_APPROVAL"})
    held = _hdr(doc, {"itm_tv": "HELD"})
    assert "ready for your YES" not in held and "on hold" in held
    done = _hdr(doc, {"itm_tv": "ACTED"})
    assert "ready for your YES" not in done and "Record the outcome of" in done and "TV flip" in done


def test_f122_mission_after_execution_shows_done_awaiting_outcome_no_deploy_headline():
    doc = _plan()
    h = mv.render_plan(doc, set(), None, {"itm_tv": "ACTED"})
    assert "DEPLOY" not in h and "awaiting the outcome" in h and "DONE" in h
    assert "<b>DEPLOY</b>" in mv.render_plan(doc, set(), None, {"itm_tv": "AWAITING_APPROVAL"})


def test_f123_each_figure_is_labelled():
    assert "not weighted by chance" in mv.render_legs([leg(title="A")], set())
    from operator_ui import summary
    import inspect
    assert "weighted by chance" in inspect.getsource(summary)


def test_f124_wanted_says_nothing_is_hunting():
    import inspect
    from operator_ui import wanted_view
    assert "No source is hunting for this yet" in inspect.getsource(wanted_view)


def test_f125_parts_comp_is_explained(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"for_item_id": "itm_m", "condition": "parts"}))
    assert cv.parts_only(str(tmp_path), "itm_m") == 1
    (tmp_path / "b.json").write_text(json.dumps({"for_item_id": "itm_m", "condition": "used"}))
    assert cv.parts_only(str(tmp_path), "itm_m") == 0
    assert cv.parts_only(str(tmp_path), "other") == 0
    assert "condition parts" in cv.saved_message("itm_m", True, "parts")
    assert "condition parts" not in cv.saved_message("itm_m", True, "used")
