"""F-23: the Wanted page. The 5x8 trailer campaign shows the right matches (02's matcher, B-20); ASSISTED_DEAL / BOUNDED_AUTOPILOT
creates are refused with the policy reason and store nothing; pause/cancel stop matching; nothing is contacted."""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from operator_ui import wanted_view
from operator_ui.server import App, make_handler
from tests.conftest import PIN
from tests.test_operator_ui import req

ROOT = Path(__file__).resolve().parent.parent
ITEMS = json.loads((ROOT / "tests/fixtures/campaign_items.json").read_text())["items"]
GOV_POLICY = next((p for p in sorted((ROOT / ".tools").glob("gov-*/policy/policy.v1.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                  if '"campaigns"' in p.read_text()), None)             # the newest pin that carries E-17


class StubStore:
    """No database: the page only reads Items and the system state."""
    lane = "reference"

    def __init__(self):
        self.calls = []

    def items_in_states(self, states):
        self.calls.append(tuple(states))
        return ITEMS

    def system_state(self):
        return "NORMAL"


@pytest.fixture()
def ui(tmp_path):
    app = App(StubStore(), operator_pin=PIN, campaigns_file=str(tmp_path / "campaigns.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


_n = iter(range(10**6))
TRAILER = {"title": "5x8 utility trailer within 40 miles, max $600", "category": "trailer", "keywords": "5x8, utility",
           "max_price_usd": "600", "radius_miles": "40", "nice_to_have": "title", "level": "RECOMMEND"}


def post(ui, path, **f):
    return req(ui, "POST", path, {"csrf": ui.csrf, "pin": PIN, "nonce": f"nonce{next(_n):08d}", **f})


def page(ui):
    return req(ui, "GET", "/wanted")[2]


def test_the_5x8_trailer_campaign_shows_the_right_matches(ui):
    status, loc, _ = post(ui, "/wanted/create", **TRAILER)
    assert status == 303 and loc.startswith("/wanted?msg=Campaign created")
    [rec] = ui.campaigns.all()
    from mbos import campaign
    campaign.validate(rec["doc"])
    assert rec["doc"]["autonomy"]["level"] == "RECOMMEND" and rec["history"][0]["by"] == "michael"
    from mbos_discovery.campaigns import match_campaign
    from mbos.clock import utcnow
    expect = [m["item_id"] for m in match_campaign(rec["doc"], ITEMS, utcnow())["matches"]]
    assert set(expect) == {"itm_%026d" % n for n in (1, 2, 4, 9, 15, 16)}   # B-20 acceptance: 6 of 16; $600 exactly is in, none above
    h = page(ui)
    for iid in expect:
        assert f"/item/{iid}" in h
    assert h.count("rank ") == 6 and "Matches " in h and "nothing was contacted" in h
    assert all(f"/item/{i['item_id']}" not in h for i in ITEMS if i["item_id"] not in expect)
    assert any("max $600" in h for _ in [0]) and "$600" in h


@pytest.mark.parametrize("level,needle", [("ASSISTED_DEAL", "ASSISTED_DEAL is refused"), ("BOUNDED_AUTOPILOT", "AUTOPILOT_NOT_AUTHORIZED"), ("GOD_MODE", "unknown autonomy")])
def test_higher_levels_are_refused_with_the_policy_reason_and_store_nothing(ui, level, needle):
    status, _, body = post(ui, "/wanted/create", **{**TRAILER, "level": level})
    assert status == 200 and needle in body and "Not saved" in body
    assert ui.campaigns.all() == []


def test_higher_levels_are_shown_but_disabled_with_the_reason(ui):
    h = page(ui)
    assert "<option value='ASSISTED_DEAL' disabled>" in h and "<option value='BOUNDED_AUTOPILOT' disabled>" in h
    assert "AUTOPILOT_NOT_AUTHORIZED" in h and "<option value='RECOMMEND' selected>" in h


@pytest.mark.skipif(GOV_POLICY is None, reason="needs the governance policy file")
def test_the_reason_comes_from_agent_05s_policy():
    r = wanted_view.level_reasons(str(GOV_POLICY))
    assert "AUTOPILOT_NOT_AUTHORIZED" in r["BOUNDED_AUTOPILOT"] and r["ASSISTED_DEAL"] != wanted_view.FALLBACK_REASONS["ASSISTED_DEAL"]


def test_no_policy_fails_closed_to_fixed_text(tmp_path):
    r = wanted_view.level_reasons(str(tmp_path / "missing.json"))
    assert r == wanted_view.FALLBACK_REASONS


def test_pause_stops_matching_resume_restores_cancel_is_final(ui):
    post(ui, "/wanted/create", **TRAILER)
    cid = ui.campaigns.all()[0]["doc"]["campaign_id"]
    post(ui, f"/wanted/{cid}/pause")
    h = page(ui)
    assert "PAUSED" in h and "not running" in h and "rank " not in h
    post(ui, f"/wanted/{cid}/resume")
    assert "rank " in page(ui)
    post(ui, f"/wanted/{cid}/cancel")
    h = page(ui)
    assert "CANCELLED" in h and "rank " not in h and "/pause" not in h
    status, _, body = post(ui, f"/wanted/{cid}/resume")
    assert "cannot resume a CANCELLED" in body
    assert [x["what"].split()[0] for x in ui.campaigns.all()[0]["history"]] == ["created", "pause", "resume", "cancel"]


def test_changes_need_csrf_and_the_pin_and_hostile_text_is_escaped(ui):
    for bad in ({"csrf": "x"}, {"pin": "0000"}, {"pin": ""}):
        f = {"csrf": ui.csrf, "pin": PIN, "nonce": "abcdefgh12", **TRAILER, **bad}
        status, _, body = req(ui, "POST", "/wanted/create", f)
        assert "Not saved" in body or status in (200, 400, 403), bad
    assert ui.campaigns.all() == []
    post(ui, "/wanted/create", **{**TRAILER, "title": "<script>alert(1)</script>"})
    h = page(ui)
    assert "<script>alert(1)" not in h and "&lt;script&gt;" in h
    status, _, body = post(ui, "/wanted/create", **{**TRAILER, "max_price_usd": "NaN"})
    assert "Not saved" in body


def test_nothing_is_contacted_or_written_to_the_spine(ui):
    post(ui, "/wanted/create", **TRAILER)
    page(ui)
    assert set(ui.store.__dict__) == {"calls"}                                   # the stub was only read
    assert all(set(c) <= set(wanted_view.OPEN_STATES) for c in ui.store.calls)


def test_the_page_says_so_when_no_campaigns_file_is_configured():
    app = App(StubStore(), operator_pin=PIN)
    app.campaigns.path = None
    from operator_ui.ux import InputError
    with pytest.raises(InputError):
        app.wanted_change({"csrf": app.csrf, "pin": PIN, "nonce": "abcdefgh12", **TRAILER})
