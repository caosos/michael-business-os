"""F-92: `mbos worker` watches the manual-comps inbox (every 60 s) and re-checks the parked (RESEARCHING) items itself, so a comp file
Michael drops in is enough: no `mbos recheck` command."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

INTERVAL_SECONDS = 60


def fingerprint(inbox: Optional[str | Path]) -> tuple:
    d = Path(inbox) if inbox else None
    if not d or not d.is_dir():
        return ()
    return tuple(sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in d.glob("*.json")))


class InboxWatcher:
    def __init__(self, inbox, parked: Callable[[], list[str]], recheck: Callable[[list[str]], list[str]]):
        self.inbox, self.parked, self.recheck, self.seen = inbox, parked, recheck, None

    def tick(self) -> list[str]:
        """Workflow ids queued this tick (empty when nothing changed). The first tick after start counts files already there."""
        fp = fingerprint(self.inbox)
        if fp == self.seen or (self.seen is None and not fp):
            self.seen = fp
            return []
        self.seen = fp
        ids = self.parked()
        return self.recheck(ids) if ids else []
