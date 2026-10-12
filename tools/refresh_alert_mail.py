#!/usr/bin/env python3
"""F-161: write the local alert-mail cache that /market reads (`var/cache/alert-mail.json`), from the owner's dedicated alerts mailbox.

Read-only IMAP through lane 02's `ImapReader` (EXAMINE + BODY.PEEK: no flag change, nothing deleted or sent). Only messages whose sender and
DKIM pass one of the alert origins are kept (everything else is dropped unread). Dry-run by default: `--live` is needed to open a connection.
Config (env, never a file): MBOS_ALERT_IMAP_HOST, MBOS_ALERT_IMAP_USER, MBOS_ALERT_IMAP_PASSWORD_ENV (the NAME of the env var that holds the
password), optional MBOS_ALERT_IMAP_FOLDER (default DealSniffer/Alerts). Its own cap: at most one read an hour (`--force` overrides).
A failed read keeps the old cache. Meant to be run by the watchdog's hourly refresh (A-72 path) with the same off switch."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mbos_discovery.adapters.email_alerts import ORIGINS, EmailAlertAdapter, ImapReader

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("MBOS_ALERT_CACHE") or ROOT / "var" / "cache" / "alert-mail.json")
EVERY = timedelta(hours=1)
MAX_MESSAGES = 300


def off() -> bool:
    return os.environ.get("MBOS_AUTO_REFRESH") == "0" or (ROOT / "var" / "watchdog" / "refresh.off").exists()


def refresh(reader, now: datetime, cache: Path = CACHE, folder: str = "") -> dict:
    """Read once, keep our senders' mail, write the cache atomically. -> a small result dict (also the receipt payload)."""
    try:
        raw = list(reader.messages(now - timedelta(days=7)))
    except Exception as e:  # noqa: BLE001  any failure keeps the old cache
        return {"result": "failed", "error": f"{type(e).__name__}: {e}"[:200], "kept": "old cache" if cache.exists() else "no cache"}
    ours = [m for m in raw if any(EmailAlertAdapter(s, reader, clock=lambda: now)._from_origin(m) for s in ORIGINS)][-MAX_MESSAGES:]
    doc = {"as_of": now.isoformat(), "mailbox_read": True, "fixture": False, "folder": folder, "messages_in_mailbox": len(raw),
           "messages": [m.decode("utf-8", "replace") for m in ours]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=cache.parent, prefix=".alert-mail-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    os.replace(tmp, cache)
    return {"result": "refreshed", "messages_in_mailbox": len(raw), "kept_from_alert_senders": len(ours), "as_of": doc["as_of"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="open the IMAP connection (read-only); without it nothing is contacted")
    ap.add_argument("--force", action="store_true", help="ignore the one-read-per-hour cap")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    if off():
        print(json.dumps({"result": "skipped", "why": "refresh off switch"}))
        return 0
    host, user, pw_env = (os.environ.get(k) for k in ("MBOS_ALERT_IMAP_HOST", "MBOS_ALERT_IMAP_USER", "MBOS_ALERT_IMAP_PASSWORD_ENV"))
    if not (host and user and pw_env and os.environ.get(pw_env)):
        print(json.dumps({"result": "not_configured", "why": "no alerts mailbox is configured on this host; the cache is left untouched"}))
        return 0
    if not a.live:
        print(json.dumps({"result": "dry_run", "why": "pass --live to read the mailbox"}))
        return 0
    try:
        last = datetime.fromisoformat(json.loads(CACHE.read_text(encoding="utf-8"))["as_of"])
    except (OSError, ValueError, KeyError):
        last = None
    if last and not a.force and now - last < EVERY:
        print(json.dumps({"result": "skipped", "why": "read less than an hour ago", "as_of": last.isoformat()}))
        return 0
    folder = os.environ.get("MBOS_ALERT_IMAP_FOLDER", "DealSniffer/Alerts")
    out = refresh(ImapReader(host, user, pw_env, folder, live=True), now, CACHE, folder)
    print(json.dumps(out))
    return 0 if out["result"] == "refreshed" else 1


if __name__ == "__main__":
    sys.exit(main())
