"""F-25: /wanted on the spine campaigns (migration 0019) through lane D's REAL Operator UI login (`mbos_operator_ui`). Create, pause,
resume and cancel are receipted (entity_type campaign, actor human:<id>); the chain verifies; ASSISTED_DEAL / AUTOPILOT are refused
and store nothing; the 5x8 example still matches (02's matcher) over the stored document."""

from __future__ import annotations

import json
import re
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


def _stored_id(loc):
    return re.search(r"cmp_[0-9A-HJKMNP-TV-Z]{26}", loc).group(0)


def test_replayed_create_names_the_stored_campaign_not_a_fresh_id(rtd, ui_least):  # F-79
    before = len(rows(rtd))
    _, loc1, _ = post(ui_least, "/wanted/create", nonce="replayF260", **TRAILER)
    _, loc2, _ = post(ui_least, "/wanted/create", nonce="replayF260", **TRAILER)
    assert _stored_id(loc1) == _stored_id(loc2) and len(rows(rtd)) == before + 1
    assert rows(rtd, _stored_id(loc2))


def test_one_malformed_stored_campaign_is_one_error_row(rtd, ui_least, monkeypatch):  # F-82
    post(ui_least, "/wanted/create", **TRAILER)
    good = ui_least.store.campaign_records()
    bad = [{"doc": {"campaign_id": "cmp_<script>", "title": 5, "criteria": {"max_price_usd": "x"}}, "history": []},
           {"doc": {}, "history": []}]
    monkeypatch.setattr(ui_least.store, "campaign_records", lambda: bad + good)
    status, _, body = req(ui_least, "GET", "/wanted")
    assert status == 200 and body.count("cannot be shown") == 2 and "<script>" not in body and TRAILER["title"] in body
    assert post(ui_least, "/wanted/cmp_nope/pause")[0] == 200  # a refusal page, not a dropped connection


def test_double_submit_loser_sees_already_recorded(rtd, ui_least, monkeypatch):  # F-84
    from operator_ui import numbers_view
    from operator_ui.backend import AlreadyRecorded

    # F-50: a withdraw needs earned capital that only earlier tests leave, and fund needs cap headroom: make the test order-independent
    real_limits = numbers_view.limits
    monkeypatch.setattr(numbers_view, "limits", lambda: {**real_limits(), "max_total_funded_usd": 10**9})
    post(ui_least, "/wanted/create", **TRAILER)
    # capital: the winner commits between the loser's lookup and its write -> the loser's insert hits the unique key
    p = post(ui_least, "/numbers/capital", kind="fund", amount="7", nonce="raceF2600")
    assert p[0] == 303
    real, calls = ui_least.store.capital_seen, []
    monkeypatch.setattr(ui_least.store, "capital_seen", lambda k, key: None if not calls and not calls.append(1) else real(k, key))

    def lose(*a, **k):
        raise AlreadyRecorded()

    monkeypatch.setattr(ui_least.store, "capital_move", lose)
    s, loc, _ = post(ui_least, "/numbers/capital", kind="fund", amount="900", nonce="raceF2600")
    assert s == 303 and "already" in loc and "7.00" in loc and "900" not in loc and "duplicate" not in loc.lower()
    assert issubclass(AlreadyRecorded, Exception)


def _race(ui, path, n, **form):
    """F-27: n threads POST the same form (same nonce) at the real server at once; returns [(status, Location, body)]."""
    import threading

    out, gate = [None] * n, threading.Barrier(n)

    def go(i):
        gate.wait()
        out[i] = post(ui, path, **form)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


def _clean(res):
    for s, loc, body in res:
        text = (loc + re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", body, flags=re.S))).lower()  # the message, not the CSS
        assert s in (303, 200), (s, loc, body[:300])
        assert not any(w in text for w in ("duplicate", "unique", "violat", "the store refused", "sqlstate", "traceback")), (loc, text[text.find("not saved"):][:400])


def test_real_concurrent_capital_double_submit_records_once_and_shows_no_db_error(rtd, ui_least, monkeypatch):  # F-27
    from operator_ui import numbers_view

    real = numbers_view.limits  # earlier tests in the session may have used up the cumulative cap; this one needs headroom
    monkeypatch.setattr(numbers_view, "limits", lambda: {**real(), "max_total_funded_usd": 10**9})
    res = _race(ui_least, "/numbers/capital", 8, kind="fund", amount="3", nonce="raceF27cap")
    _clean(res)
    with rtd.engine.connect() as c:
        n = c.execute(sa.text("SELECT count(*) FROM mbos.receipts WHERE idempotency_key LIKE '%raceF27cap'")).scalar()
    assert n == 1
    assert sum(1 for s, loc, _ in res if "already" in loc) >= 1


def test_real_concurrent_wanted_create_double_submit_records_once_and_shows_no_db_error(rtd, ui_least):  # F-27
    before = len(rows(rtd))
    res = _race(ui_least, "/wanted/create", 8, nonce="raceF27wnt", **TRAILER)
    _clean(res)
    assert len(rows(rtd)) == before + 1
    assert sum(1 for s, loc, b in res if "already" in (loc + b)) >= 1
