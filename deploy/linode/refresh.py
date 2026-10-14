# DealSniffer-managed. Hourly listings refresh for the public site (dealsniffer-refresh.timer, runs as the `dealsniffer` user).
"""Free, permitted routes only:
  * GSA Auctions official API (api.gsa.gov) through lane 02's GsaLiveAdapter: the owner's free api.data.gov key from
    /etc/dealsniffer/gsa.key when present, else the shared DEMO_KEY. At most one fetch an hour; after a failure wait 30 min,
    after a rate-limit (429) wait an hour. The new file replaces the cache only when it parses and lists at least one lot.
  * Auction-house EVENTS from the auctioneers' own pages (Wooley, Wilson, Blackmon) through the release's
    tools/refresh_auction_events.py --live (its own crawl delays and hourly caps; never hibid/bidwrangler/proxibid).
No paid provider exists in the release (Facebook/Bright Data are denied in code); nothing here can call one."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REL = Path(os.environ.get("DS_RELEASE", "/opt/dealsniffer/current"))
CACHE = Path(os.environ.get("MBOS_GSA_CACHE", "/var/lib/dealsniffer/cache/gsa-active-auctions.json"))
KEY_FILE = Path(os.environ.get("DS_GSA_KEY_FILE", "/etc/dealsniffer/gsa.key"))
ALERTS_ENV = Path(os.environ.get("DS_ALERTS_ENV", "/etc/dealsniffer/alerts.env"))
EVERY, RETRY, LIMITED = timedelta(hours=1), timedelta(minutes=30), timedelta(hours=1)


def log(**kv) -> None:
    print(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **kv}, sort_keys=True), flush=True)


def gsa_key() -> str:
    try:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        key = ""
    return key if re.fullmatch(r"[A-Za-z0-9]{20,64}", key) else "DEMO_KEY"


def _asof(p: Path):
    try:
        return datetime.fromisoformat(p.with_suffix(".asof").read_text().strip().replace("Z", "+00:00"))
    except (OSError, ValueError):
        return None


def _lots(p: Path) -> int:
    try:
        rows = json.loads(p.read_text()).get("Results")
    except (OSError, ValueError, AttributeError):
        return 0
    return len(rows) if isinstance(rows, list) else 0


def _fetch(tmp: Path) -> str | None:
    """One logical GSA fetch into `tmp` (+ .asof). Returns an error message or None."""
    from mbos_discovery.adapter import SearchProfile
    from mbos_discovery.gsa_live import GsaLiveAdapter
    res = GsaLiveAdapter(tmp, live=True, api_key=gsa_key()).fetch(SearchProfile("market", "flip"))
    err = getattr(res, "error", None)
    return str(getattr(err, "message", err))[:200] if err else None


def refresh_gsa(now: datetime, fetch=_fetch) -> dict:
    last = _asof(CACHE)
    if last is not None and now - last < EVERY:
        return {"source": "gsa", "result": "not due", "as_of": last.isoformat()}
    attempt = CACHE.with_suffix(".attempt")
    try:
        prev = json.loads(attempt.read_text())
        wait = LIMITED if prev.get("rate_limited") else RETRY
        if prev.get("result") == "failed" and now - datetime.fromisoformat(prev["at"]) < wait:
            return {"source": "gsa", "result": "backing off", "until": (datetime.fromisoformat(prev["at"]) + wait).isoformat()}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix=".gsa-refresh-", dir=CACHE.parent))
    tmp = tmpdir / CACHE.name
    try:
        err = fetch(tmp)
        n = 0 if err else _lots(tmp)
        if err or not n or not tmp.with_suffix(".asof").exists():
            out = {"source": "gsa", "result": "failed", "error": err or "fetched file missing, unparseable or empty", "kept": "old cache"}
        else:
            os.replace(tmp, CACHE)
            os.replace(tmp.with_suffix(".asof"), CACHE.with_suffix(".asof"))
            out = {"source": "gsa", "result": "refreshed", "lots_in_file": n, "as_of": CACHE.with_suffix(".asof").read_text().strip(),
                   "key": "owner" if gsa_key() != "DEMO_KEY" else "DEMO_KEY"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    e = str(out.get("error") or "")
    attempt.write_text(json.dumps({"at": now.isoformat(), "result": out["result"], "rate_limited": "429" in e or "OVER_RATE_LIMIT" in e}))
    return out


def refresh_events() -> dict:
    tool = REL / "tools" / "refresh_auction_events.py"
    if not tool.is_file():
        return {"source": "auction_houses", "result": "skipped", "error": "tool not in this release"}
    p = subprocess.run([sys.executable, str(tool), "--live"], cwd=str(REL), capture_output=True, text=True, timeout=900)
    tail = (p.stdout + p.stderr).strip().splitlines()[-6:]
    return {"source": "auction_houses", "result": "ok" if p.returncode == 0 else f"exit {p.returncode}", "output": tail}


def refresh_alerts() -> dict:
    """Craigslist / GovDeals / Public Surplus saved-search ALERT E-MAILS from the dedicated alerts mailbox (read-only IMAP; the tool keeps
    only DKIM-verified alert senders, never changes flags, at most one read an hour). Off until the owner writes alerts.env."""
    tool = REL / "tools" / "refresh_alert_mail.py"
    try:
        pairs = dict(l.split("=", 1) for l in ALERTS_ENV.read_text(encoding="utf-8").splitlines() if "=" in l and not l.startswith("#"))
    except OSError:
        return {"source": "alert_mail", "result": "not set up", "why": f"{ALERTS_ENV} absent (configure_alerts.sh)"}
    if not tool.is_file():
        return {"source": "alert_mail", "result": "skipped", "error": "tool not in this release"}
    env = {**os.environ, "MBOS_ALERT_IMAP_HOST": pairs.get("MBOS_ALERT_IMAP_HOST", "imap.gmail.com"), "MBOS_ALERT_IMAP_USER": pairs.get("MBOS_ALERT_IMAP_USER", ""),
           "MBOS_ALERT_IMAP_PASSWORD_ENV": "MBOS_IMAP_PASSWORD", "MBOS_IMAP_PASSWORD": pairs.get("MBOS_IMAP_PASSWORD", ""),
           "MBOS_ALERT_IMAP_FOLDER": pairs.get("MBOS_ALERT_IMAP_FOLDER", "INBOX")}
    p = subprocess.run([sys.executable, str(tool), "--live"], cwd=str(REL), env=env, capture_output=True, text=True, timeout=300)
    out = "\n".join((p.stdout + p.stderr).strip().splitlines()[-4:]).replace(env["MBOS_IMAP_PASSWORD"] or "\0", "[redacted]")
    return {"source": "alert_mail", "result": "ok" if p.returncode == 0 else f"exit {p.returncode}", "output": out.splitlines()}


def main() -> int:
    now = datetime.now(timezone.utc)
    log(**refresh_gsa(now))
    log(**refresh_events())
    log(**refresh_alerts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
