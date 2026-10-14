"""A-72: keep the live caches fresh from INSIDE the existing local watchdog (no new service).

* GSA (`var/cache/gsa-active-auctions.json`): at most once per hour, through the supported lane 02 route
  `GsaLiveAdapter(path, live=True)` (DEMO_KEY, one logical fetch). The fetch goes to a temporary file; only a parseable file with a
  non-empty `Results` list replaces the live one, after a backup to `var/cache/prev-<UTC>/` (the newest 5 backups are kept). A failure
  keeps the old cache.
* Auction houses: the release-installed `var/lanes/agent-06/tools/refresh_auction_events.py --live` (it keeps its own hourly caps
  and never replaces a good cache with an empty one), started in the BACKGROUND so the watchdog is never blocked; one run at a time.
* Never while a release or reload is running. Off switch: the file `var/watchdog/refresh.off` (or env MBOS_AUTO_REFRESH=0).
Every action returns a small dict that the watchdog writes as a hash-chained receipt.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

GSA_EVERY = timedelta(hours=1)
GSA_RETRY = timedelta(minutes=30)          # S2: after a failed fetch, wait before trying again (was: every watchdog tick, ~2 min)
GSA_RATE_LIMITED = timedelta(hours=1)      # after an api.data.gov 429, wait a full window: retries inside it only extend the block
EVENTS_EVERY = timedelta(hours=1)
KEEP_BACKUPS = 5


def off(root: Path) -> bool:
    return os.environ.get("MBOS_AUTO_REFRESH") == "0" or (root / "var" / "watchdog" / "refresh.off").exists()


def release_running(ps_lines: list[str]) -> bool:
    return any(re.search(r"(release_marketplace\.sh|reload_ui\.sh)\s", x) and "grep" not in x for x in ps_lines)


def _asof(p: Path) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(p.with_suffix(".asof").read_text().strip().replace("Z", "+00:00"))
    except (OSError, ValueError):
        return None


def gsa_api_key() -> str:
    """The owner's free api.data.gov key (env GSA_API_KEY or ~/.config/mbos/secrets/GSA_API_KEY, mode 600), else the shared DEMO_KEY.
    Never logged. The shared DEMO_KEY allows about 30 calls an hour and 50 a day per address, which the hourly refresh can exhaust."""
    key = os.environ.get("GSA_API_KEY", "").strip()
    if not key:
        try:
            key = Path("~/.config/mbos/secrets/GSA_API_KEY").expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
    return key if re.fullmatch(r"[A-Za-z0-9]{20,64}", key) else "DEMO_KEY"


def _valid(p: Path) -> int:
    try:
        rows = json.loads(p.read_text()).get("Results")
    except (OSError, ValueError, AttributeError):
        return 0
    return len(rows) if isinstance(rows, list) else 0


def refresh_gsa(root: Path, now: datetime, fetch: Optional[Callable[[Path], object]] = None) -> Optional[dict]:
    """None when not due; else a receipt dict. `fetch(tmp_cache_path)` defaults to the lane 02 adapter (one logical fetch)."""
    cache = root / "var" / "cache" / "gsa-active-auctions.json"
    last = _asof(cache)
    if last is not None and now - last < GSA_EVERY:
        return None
    attempt_file = cache.with_suffix(".attempt")
    try:
        prev = json.loads(attempt_file.read_text())
        wait = GSA_RATE_LIMITED if prev.get("rate_limited") else GSA_RETRY
        if prev.get("result") == "failed" and now - datetime.fromisoformat(prev["at"]) < wait:
            return None
    except (OSError, ValueError, KeyError, TypeError):
        pass
    out = _refresh_gsa(cache, now, fetch)
    err = str(out.get("error") or "")
    attempt_file.write_text(json.dumps({"at": now.isoformat(), "result": out["result"],
                                        "rate_limited": "429" in err or "OVER_RATE_LIMIT" in err}))
    return out


def _refresh_gsa(cache: Path, now: datetime, fetch) -> dict:
    tmpdir = Path(tempfile.mkdtemp(prefix=".gsa-refresh-", dir=cache.parent))
    tmp = tmpdir / cache.name
    try:
        if fetch is None:
            from mbos_discovery.adapter import SearchProfile
            from mbos_discovery.gsa_live import GsaLiveAdapter
            res = GsaLiveAdapter(tmp, live=True, api_key=gsa_api_key()).fetch(SearchProfile("market", "flip"))
            err = getattr(res, "error", None)
            if err:
                return {"source": "gsa", "result": "failed", "error": str(getattr(err, "message", err))[:200], "kept": "old cache"}
        else:
            fetch(tmp)
        n = _valid(tmp)
        if not n or not tmp.with_suffix(".asof").exists():
            return {"source": "gsa", "result": "failed", "error": "fetched file missing, unparseable or empty", "kept": "old cache"}
        backup = cache.parent / ("prev-" + now.strftime("%Y%m%dT%H%M%SZ"))
        if cache.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cache, backup / cache.name)
            if cache.with_suffix(".asof").exists():
                shutil.copy2(cache.with_suffix(".asof"), backup / cache.with_suffix(".asof").name)
        os.replace(tmp, cache)                                   # same filesystem: atomic
        os.replace(tmp.with_suffix(".asof"), cache.with_suffix(".asof"))
        for old in sorted(cache.parent.glob("prev-*"))[:-KEEP_BACKUPS]:
            shutil.rmtree(old, ignore_errors=True)
        return {"source": "gsa", "result": "refreshed", "lots_in_file": n, "as_of": cache.with_suffix(".asof").read_text().strip(),
                "backup": str(backup) if backup.exists() else None}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def start_events_refresh(root: Path, now: datetime, state: dict, ps_lines: list[str],
                         spawn: Optional[Callable[[list[str]], int]] = None) -> Optional[dict]:
    """Start (never wait for) one background auction-house refresh per hour; None when not due or already running."""
    tool = root / "var" / "lanes" / "agent-06" / "tools" / "refresh_auction_events.py"
    if not tool.exists():
        return None
    if any("refresh_auction_events.py" in x and "--live" in x and "grep" not in x for x in ps_lines):
        return None
    last = state.get("events_refresh_started")
    if last and now - datetime.fromisoformat(last) < EVENTS_EVERY:
        return None
    cmd = [str(root / ".venv" / "bin" / "python"), str(tool), "--live"]
    log = root / "var" / "watchdog" / "events-refresh.log"
    if spawn is None:
        def spawn(c):                                           # detached, output to a log; the watchdog does not wait
            with open(log, "a") as f:
                return subprocess.Popen(c, cwd=str(root / "var" / "lanes" / "agent-06"), stdout=f, stderr=subprocess.STDOUT,
                                        start_new_session=True).pid
    pid = spawn(cmd)
    state["events_refresh_started"] = now.isoformat()
    return {"source": "auction_houses", "result": "started", "pid": pid, "log": str(log)}


ALERTS_EVERY = timedelta(hours=1)
MAILBOX_CONFIG = Path.home() / ".config" / "mbos" / "discovery-alerts.toml"
MAILBOX_SECRET = Path.home() / ".config" / "mbos" / "imap.env"


def alerts_env(config: Path = MAILBOX_CONFIG, secret: Path = MAILBOX_SECRET) -> Optional[dict]:
    """F-161 env for the release-installed refresh_alert_mail.py, or None when the dedicated mailbox is not set up.
    The password goes only into the child's environment; it is never logged or put in a receipt."""
    try:
        import tomllib
        imap = tomllib.loads(config.read_text())["profile"][0]["imap"]
        pw = next((ln.split("=", 1)[1].strip() for ln in secret.read_text().splitlines() if ln.startswith("MBOS_IMAP_PASSWORD=")), "")
    except (OSError, ValueError, KeyError, IndexError):
        return None
    user = imap.get("user") or ""
    if not pw or "@" not in user or "SET-ME" in user:
        return None
    return {"MBOS_ALERT_IMAP_HOST": imap.get("host", "imap.gmail.com"), "MBOS_ALERT_IMAP_USER": user,
            "MBOS_ALERT_IMAP_PASSWORD_ENV": "MBOS_IMAP_PASSWORD", "MBOS_IMAP_PASSWORD": pw,
            "MBOS_ALERT_IMAP_FOLDER": imap.get("folder", "INBOX")}     # the dedicated alerts mailbox's inbox; no Gmail label is required


def start_alerts_refresh(root: Path, now: datetime, state: dict, ps_lines: list[str],
                         spawn: Optional[Callable[[list[str], dict], int]] = None, env: Optional[dict] = None) -> Optional[dict]:
    """Start (never wait for) one background read-only alert-mailbox refresh per hour; None when not due, running or not set up."""
    tool = root / "var" / "lanes" / "agent-06" / "tools" / "refresh_alert_mail.py"
    if not tool.exists():
        return None
    if any("refresh_alert_mail.py" in x and "--live" in x and "grep" not in x for x in ps_lines):
        return None
    last = state.get("alerts_refresh_started")
    if last and now - datetime.fromisoformat(last) < ALERTS_EVERY:
        return None
    env = env if env is not None else alerts_env()
    if not env:
        return None
    cmd = [str(root / ".venv" / "bin" / "python"), str(tool), "--live"]
    log = root / "var" / "watchdog" / "alerts-refresh.log"
    if spawn is None:
        def spawn(c, e):                                        # detached, output to a log; the watchdog does not wait
            with open(log, "a") as f:
                return subprocess.Popen(c, cwd=str(root / "var" / "lanes" / "agent-06"), stdout=f, stderr=subprocess.STDOUT,
                                        env={**os.environ, **e}, start_new_session=True).pid
    pid = spawn(cmd, env)
    state["alerts_refresh_started"] = now.isoformat()
    return {"source": "alert_mail", "result": "started", "pid": pid, "mailbox": env["MBOS_ALERT_IMAP_USER"], "log": str(log)}


def tick(root: Path, now: datetime, state: dict, ps_lines: list[str], *, gsa_fetch=None, spawn=None, alerts_spawn=None,
         alerts_env_=None) -> list[dict]:
    if off(root):
        return []
    if release_running(ps_lines):
        return [{"source": "all", "result": "skipped", "why": "a release/reload is running"}]
    out = []
    g = refresh_gsa(root, now, gsa_fetch)
    if g:
        out.append(g)
    e = start_events_refresh(root, now, state, ps_lines, spawn)
    if e:
        out.append(e)
    m = start_alerts_refresh(root, now, state, ps_lines, alerts_spawn, alerts_env_)
    if m:
        out.append(m)
    return out
