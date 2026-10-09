"""F-45: My notes has its own Add note path (owner channel, CSRF + PIN), on lane D + lane E."""
from tests.conftest import PIN
from tests.lane_d.test_notes_f14 import NOTE
from tests.lane_d.test_ui_on_lane_d import req


def test_add_note_from_my_notes(ui_d):
    page = req(ui_d, "GET", "/notes")[2]
    assert "<summary><b>Add note</b></summary>" in page and "action='/notes/add'" in page and 'name="author"' not in page
    assert req(ui_d, "POST", "/notes/add", {**NOTE, "pin": PIN})[2].count("invalid form token") >= 1                 # no CSRF
    before = len(ui_d.store.operator_notes())
    assert "PIN" in req(ui_d, "POST", "/notes/add", {"csrf": ui_d.csrf, "pin": "0000", **NOTE})[2]                   # wrong PIN
    assert len(ui_d.store.operator_notes()) == before
    s, loc, _ = req(ui_d, "POST", "/notes/add", {"csrf": ui_d.csrf, "pin": PIN, **NOTE, "statement": "F45 <b>marker</b> torsion axle seats corrode by year six."})
    assert s == 303 and loc.startswith("/notes?msg=Note saved (mn_"), loc
    (n,) = [x for x in ui_d.store.operator_notes() if "F45" in x["statement"]]
    assert n["entered_by"] == "michael" and n["basis"] == "RECOMMENDATION"
    page = req(ui_d, "GET", "/notes")[2]
    assert "F45 &lt;b&gt;marker&lt;/b&gt;" in page and "F45 <b>marker</b>" not in page
    s, _, out = req(ui_d, "POST", "/notes/add", {"csrf": ui_d.csrf, "pin": PIN, **NOTE, "category": "nonsense"})
    assert s == 200 and "Not saved" in out
