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
    tmpdir = Path(tempfile.mkdtemp(prefix=".gsa-refresh-", dir=cache.parent))
    tmp = tmpdir / cache.name
    try:
        if fetch is None:
            from mbos_discovery.adapter import SearchProfile
            from mbos_discovery.gsa_live import GsaLiveAdapter
            res = GsaLiveAdapter(tmp, live=True).fetch(SearchProfile("market", "flip"))
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


def tick(root: Path, now: datetime, state: dict, ps_lines: list[str], *, gsa_fetch=None, spawn=None) -> list[dict]:
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
    return out
