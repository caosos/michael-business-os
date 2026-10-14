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
    for i, bad in enumerate((good_fetch(0), lambda tmp: tmp.write_text("not json"))):
        out = cr.refresh_gsa(r, NOW + i * cr.GSA_RETRY, bad)          # S2: a retry needs the back-off interval
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


def test_alerts_refresh_background_hourly_single_and_secret_free(tmp_path):
    r = root_with_cache(tmp_path, NOW)
    tool = r / "var/lanes/agent-06/tools/refresh_alert_mail.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("# stub")
    env = {"MBOS_ALERT_IMAP_HOST": "imap.gmail.com", "MBOS_ALERT_IMAP_USER": "alerts@example.com",
           "MBOS_ALERT_IMAP_PASSWORD_ENV": "MBOS_IMAP_PASSWORD", "MBOS_IMAP_PASSWORD": "sekret-app-pw", "MBOS_ALERT_IMAP_FOLDER": "DealSniffer/Alerts"}
    spawned, st = [], {}
    sp = lambda c, e: spawned.append((c, e)) or 5151  # noqa: E731
    a = cr.start_alerts_refresh(r, NOW, st, [], sp, env)
    assert a["pid"] == 5151 and a["mailbox"] == "alerts@example.com" and "sekret" not in json.dumps(a)   # receipt never carries the password
    assert spawned[0][0][-1] == "--live" and spawned[0][1]["MBOS_IMAP_PASSWORD"] == "sekret-app-pw"      # only the child env does
    assert cr.start_alerts_refresh(r, NOW + timedelta(minutes=30), st, [], sp, env) is None              # hourly
    running = ["  8 /x/.venv/bin/python /r/var/lanes/agent-06/tools/refresh_alert_mail.py --live"]
    assert cr.start_alerts_refresh(r, NOW + timedelta(hours=2), st, running, sp, env) is None            # one at a time
    assert cr.start_alerts_refresh(r, NOW + timedelta(hours=2), {}, [], sp, {}) is None                  # mailbox not set up: nothing
    assert len(spawned) == 1


def test_alerts_env_needs_a_real_address_and_password(tmp_path):
    cfg, sec = tmp_path / "a.toml", tmp_path / "imap.env"
    cfg.write_text('[[profile]]\nid = "x"\nimap = { host = "imap.gmail.com", user = "SET-ME-dedicated-alerts-address", folder = "DealSniffer/Alerts" }\n')
    sec.write_text("MBOS_IMAP_PASSWORD=abcdefghijklmnop\n")
    assert cr.alerts_env(cfg, sec) is None                                                               # placeholder address
    cfg.write_text('[[profile]]\nid = "x"\nimap = { host = "imap.gmail.com", user = "alerts@example.com", folder = "DealSniffer/Alerts" }\n')
    assert cr.alerts_env(cfg, sec)["MBOS_ALERT_IMAP_USER"] == "alerts@example.com"
    sec.write_text("")
    assert cr.alerts_env(cfg, sec) is None                                                               # no password
    assert cr.alerts_env(tmp_path / "missing.toml", sec) is None


def test_failed_gsa_fetch_backs_off_instead_of_retrying_every_tick(tmp_path):
    """S2: a failed fetch waits 30 min; a 429 (api.data.gov rate limit) waits an hour. It used to retry every 2-minute tick."""
    r = root_with_cache(tmp_path, NOW - timedelta(hours=3))
    calls = []

    def empty(tmp: Path):
        calls.append(1)
    assert cr.refresh_gsa(r, NOW, empty)["result"] == "failed"
    assert cr.refresh_gsa(r, NOW + timedelta(minutes=2), empty) is None
    assert cr.refresh_gsa(r, NOW + timedelta(minutes=29), empty) is None
    assert cr.refresh_gsa(r, NOW + timedelta(minutes=31), good_fetch())["result"] == "refreshed"
    assert len(calls) == 1
    att = json.loads((r / "var/cache/gsa-active-auctions.attempt").read_text())
    assert att["result"] == "refreshed" and att["rate_limited"] is False


def test_rate_limited_gsa_fetch_waits_a_full_hour(tmp_path, monkeypatch):
    r = root_with_cache(tmp_path, NOW - timedelta(hours=3))
    monkeypatch.setattr(cr, "_refresh_gsa", lambda cache, now, fetch: {"source": "gsa", "result": "failed",
                                                                       "error": "429 from GSA Auctions: OVER_RATE_LIMIT", "kept": "old cache"})
    assert cr.refresh_gsa(r, NOW)["result"] == "failed"
    assert json.loads((r / "var/cache/gsa-active-auctions.attempt").read_text())["rate_limited"] is True
    assert cr.refresh_gsa(r, NOW + timedelta(minutes=45)) is None
    assert cr.refresh_gsa(r, NOW + timedelta(minutes=61))["result"] == "failed"


def test_gsa_key_comes_from_env_or_host_file_else_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("GSA_API_KEY", raising=False)
    assert cr.gsa_api_key() == "DEMO_KEY"
    f = tmp_path / ".config/mbos/secrets/GSA_API_KEY"
    f.parent.mkdir(parents=True)
    f.write_text("abcdefghijklmnopqrstuvwxyz0123456789ABCD\n")
    assert cr.gsa_api_key() == "abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    monkeypatch.setenv("GSA_API_KEY", "not a key!")
    assert cr.gsa_api_key() == "DEMO_KEY"                               # malformed never reaches a URL

