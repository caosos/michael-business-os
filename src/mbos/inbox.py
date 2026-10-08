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


class ResearchWatcher:
    """F-109: re-check a parked item when its research grew (a UI attestation or comp), not only when the inbox changed.
    `lengths() -> {item_id: len(research)}` for the parked (RESEARCHING) items. An item seen for the first time is only baselined
    (the inbox watcher and the worker start already cover what existed). The length seen is recorded BEFORE the re-check runs, and the
    re-check's own research entries are absorbed into the baseline on the following tick without queueing again."""

    def __init__(self, lengths: Callable[[], dict[str, int]], recheck: Callable[[list[str]], list[str]]):
        self.lengths, self.recheck, self.seen, self.pending = lengths, recheck, {}, set()

    def tick(self) -> list[str]:
        now = self.lengths()
        grown = []
        for iid, n in now.items():
            if iid in self.seen and n > self.seen[iid]:
                if iid in self.pending:  # grew because our own re-check wrote research: absorb it
                    self.pending.discard(iid)
                else:
                    grown.append(iid)
            self.seen[iid] = n
        for iid in list(self.seen):
            if iid not in now:  # left RESEARCHING: forget it, so a later park starts from a fresh baseline
                del self.seen[iid]
                self.pending.discard(iid)
        if not grown:
            self.pending.clear()
            return []
        self.pending = set(grown)
        return self.recheck(grown)
