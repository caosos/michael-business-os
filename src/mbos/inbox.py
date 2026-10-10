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
    """F-109 / A-50: re-check a parked item when a HUMAN added evidence (a UI attestation, a quote, an override), not only when the inbox changed.
    `lengths() -> {item_id: n}` counts the parked (RESEARCHING) items' HUMAN-written research entries only, so the re-check's own research never
    counts as growth and nothing has to be absorbed: a human input that lands in the round after a re-check is still seen (the old
    absorb-the-next-growth rule swallowed it). An item seen for the first time is only baselined (the inbox watcher and the worker start
    already cover what existed); the count is recorded BEFORE the re-check runs."""

    def __init__(self, lengths: Callable[[], dict[str, int]], recheck: Callable[[list[str]], list[str]]):
        self.lengths, self.recheck, self.seen = lengths, recheck, {}

    def tick(self) -> list[str]:
        now = self.lengths()
        grown = [iid for iid, n in now.items() if iid in self.seen and n > self.seen[iid]]
        self.seen = dict(now)  # an item that left RESEARCHING is forgotten, so a later park starts from a fresh baseline
        return self.recheck(grown) if grown else []


class HumanInputWatcher:
    """A-43: re-check a parked item when Michael enters a new `quote:` / `scope_override:` entry. Counts ONLY those human entries, which a
    re-check never writes, so (unlike ResearchWatcher) nothing of its own has to be absorbed and an input made during a re-check is not lost.
    `counts() -> {item_id: n}` for the parked (RESEARCHING) items; an item seen for the first time is only baselined."""

    def __init__(self, counts: Callable[[], dict[str, int]], recheck: Callable[[list[str]], list[str]]):
        self.counts, self.recheck, self.seen = counts, recheck, {}

    def tick(self) -> list[str]:
        now = self.counts()
        grown = [iid for iid, n in now.items() if iid in self.seen and n > self.seen[iid]]
        self.seen = dict(now)
        return self.recheck(grown) if grown else []
