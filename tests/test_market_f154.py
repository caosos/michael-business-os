"""F-154: closing-soon badges (2 h / today, America/Chicago), sorted first; ended date source. Display only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from operator_ui import market_autobids as mba
from operator_ui import market_bids as mb

U = timezone.utc
T = lambda s: datetime.fromisoformat(s)  # noqa: E731


def test_two_hour_boundary():
    now = T("2026-10-12T15:00:00+00:00")
    at = lambda d: {"closes_at": (now + d).isoformat()}  # noqa: E731
    assert mb.closing(at(timedelta(hours=2)), now) == "closing within 2 h"
    assert mb.closing(at(timedelta(hours=2, seconds=1)), now) == "closing today"
    assert mb.closing(at(timedelta(seconds=1)), now) == "closing within 2 h"
    assert mb.closing(at(timedelta(0)), now) == "" and mb.closing(at(-timedelta(minutes=1)), now) == ""
    assert mb.closing({"closes_at": "", "closes": ""}, now) == ""


def test_today_boundary_cdt():           # Oct 12 2026 is CDT (UTC-5): midnight Chicago = 05:00Z
    now = T("2026-10-12T14:00:00+00:00")                       # 09:00 CDT
    assert mb.closing({"closes_at": "2026-10-13T04:59:59+00:00"}, now) == "closing today"   # 23:59:59 CDT
    assert mb.closing({"closes_at": "2026-10-13T05:00:00+00:00"}, now) == ""                # 00:00 CDT tomorrow
    assert mb.closing({"closes": "2026-10-12"}, now) == "closing today"                     # date only = end of day Chicago
    assert mb.closing({"closes": "2026-10-13"}, now) == ""


def test_today_boundary_cst():           # Nov 10 2026 is CST (UTC-6): midnight Chicago = 06:00Z
    now = T("2026-11-10T15:00:00+00:00")                       # 09:00 CST
    assert mb.closing({"closes_at": "2026-11-11T05:59:59+00:00"}, now) == "closing today"
    assert mb.closing({"closes_at": "2026-11-11T06:00:00+00:00"}, now) == ""
    late = T("2026-11-11T05:30:00+00:00")                      # 23:30 CST on the 10th: UTC date is already the 11th
    assert mb.closing({"closes_at": "2026-11-11T05:45:00+00:00"}, late) == "closing within 2 h"
    assert mb.closing({"closes_at": "2026-11-11T08:00:00+00:00"}, late) == ""               # 02:00 CST on the 11th


def test_window_sorts_badged_first_and_shows_badges():
    now = T("2026-10-12T14:00:00+00:00")
    bid = lambda t, c: {"title": t, "source": "s", "url": "", "closes": "", "closes_at": c, "bid": None, "bidders": None, "fetched_at": ""}  # noqa: E731
    d = {"bids": {"a": bid("Later", "2026-10-20T12:00:00+00:00"), "b": bid("Tonight", "2026-10-13T03:00:00+00:00"), "c": bid("Soon", "2026-10-12T15:00:00+00:00"),
                  "d": bid("Gone", "2026-10-12T10:00:00+00:00")}}
    h = mb.window(d, [], now, lambda: "")
    order = [h.index(x) for x in ("Soon", "Tonight", "Gone", "Later")]
    assert order == sorted(order)
    assert h.count("CLOSING WITHIN 2 H") == 1 and h.count("CLOSING TODAY") == 1


def test_ended_auto_row_date_source():
    now = T("2026-10-12T14:00:00+00:00")
    rec = {"id": "auto:x:1", "source": "hibid", "title": "T", "url": "https://x/1", "event": "won", "observed_at": "2026-10-12T14:00:00Z",
           "provenance": {"message_id": "<m>"}, "closes_at": "2026-10-12T15:00:00+00:00"}
    run = lambda r: mba.rows([r], now, lambda: "", mb.countdown, mb._end, mb.badge, mb._rank)[0][2]  # noqa: E731
    h = run(rec)
    assert "ended (read 2026-10-12)" in h and "CLOSING" not in h
    assert "ended (per your e-mail, 2026-10-09)" in run({**rec, "email_date": "2026-10-09T08:00:00-05:00"})
    live = run({**rec, "event": "winning"})
    assert "CLOSING WITHIN 2 H" in live
