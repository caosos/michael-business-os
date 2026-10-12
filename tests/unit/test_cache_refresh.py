"""A-72: scheduled cache refresh inside the watchdog (tools/cache_refresh.py), no network."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("cr", Path(__file__).resolve().parents[2] / "tools" / "cache_refresh.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def root_with_cache(tmp_path, asof: datetime, rows=3):
    c = tmp_path / "var" / "cache"
    c.mkdir(parents=True)
    (c / "gsa-active-auctions.json").write_text(json.dumps({"Results": [{"lotNo": i} for i in range(rows)]}))
    (c / "gsa-active-auctions.asof").write_text(asof.strftime("%Y-%m-%dT%H:%M:%SZ"))
    (tmp_path / "var" / "watchdog").mkdir(parents=True)
    return tmp_path


def good_fetch(n=7):
    def f(tmp: Path):
        tmp.write_text(json.dumps({"Results": [{"lotNo": i} for i in range(n)]}))
        tmp.with_suffix(".asof").write_text(NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return f


def test_gsa_not_due_within_an_hour_then_refreshes_with_a_backup(tmp_path):
    r = root_with_cache(tmp_path, NOW - timedelta(minutes=30))
    assert cr.refresh_gsa(r, NOW, good_fetch()) is None
    r2 = root_with_cache(tmp_path / "b", NOW - timedelta(hours=2))
    out = cr.refresh_gsa(r2, NOW, good_fetch())
    assert out["result"] == "refreshed" and out["lots_in_file"] == 7
    assert json.loads((r2 / "var/cache/gsa-active-auctions.json").read_text())["Results"][6] == {"lotNo": 6}
    assert len(json.loads((Path(out["backup"]) / "gsa-active-auctions.json").read_text())["Results"]) == 3


def test_failed_or_empty_fetch_keeps_the_old_cache(tmp_path):
    r = root_with_cache(tmp_path, NOW - timedelta(hours=2))
    for bad in (good_fetch(0), lambda tmp: tmp.write_text("not json")):
        out = cr.refresh_gsa(r, NOW, bad)
        assert out["result"] == "failed" and out["kept"] == "old cache"
        assert len(json.loads((r / "var/cache/gsa-active-auctions.json").read_text())["Results"]) == 3
    assert not list((r / "var/cache").glob(".gsa-refresh-*"))           # temp dirs cleaned


def test_only_the_newest_five_backups_are_kept(tmp_path):
    r = root_with_cache(tmp_path, NOW - timedelta(hours=2))
    for h in range(7):
        t = NOW + timedelta(hours=2 * h)
        (r / "var/cache/gsa-active-auctions.asof").write_text((t - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        cr.refresh_gsa(r, t, good_fetch())
    assert len(list((r / "var/cache").glob("prev-*"))) == 5


def test_events_refresh_is_background_hourly_and_single(tmp_path):
    r = root_with_cache(tmp_path, NOW)
    tool = r / "var/lanes/agent-06/tools/refresh_auction_events.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("# stub")
    spawned, st = [], {}
    sp = lambda c: spawned.append(c) or 4242  # noqa: E731
    assert cr.start_events_refresh(r, NOW, st, [], sp)["pid"] == 4242
    assert cr.start_events_refresh(r, NOW + timedelta(minutes=30), st, [], sp) is None              # hourly
    running = ["  7 /x/.venv/bin/python /r/var/lanes/agent-06/tools/refresh_auction_events.py --live"]
    assert cr.start_events_refresh(r, NOW + timedelta(hours=2), st, running, sp) is None            # one at a time
    assert len(spawned) == 1 and spawned[0][-1] == "--live"


def test_release_guard_and_off_switch(tmp_path, monkeypatch):
    r = root_with_cache(tmp_path, NOW - timedelta(hours=2))
    rel = ["  9 bash tools/release_marketplace.sh abc def"]
    assert cr.tick(r, NOW, {}, rel, gsa_fetch=good_fetch()) == [{"source": "all", "result": "skipped", "why": "a release/reload is running"}]
    (r / "var/watchdog/refresh.off").write_text("")
    assert cr.tick(r, NOW, {}, [], gsa_fetch=good_fetch()) == []
    (r / "var/watchdog/refresh.off").unlink()
    monkeypatch.setenv("MBOS_AUTO_REFRESH", "0")
    assert cr.tick(r, NOW, {}, [], gsa_fetch=good_fetch()) == []
