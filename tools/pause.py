"""Owner pause switch for Deal Sniffer / MBOS MODEL work. If `var/PAUSED_BY_OWNER` exists, nothing may start a model job:
tools/dispatcher.py exits, tools/worker.py refuses to launch, and tools/inbox_pickup.py will not run a WORK executor (zero-model PING and
heartbeat still work). Resume = delete the file (see docs/status/PAUSED_BY_OWNER.md)."""
import json
from pathlib import Path
from typing import Optional

FLAG = Path(__file__).resolve().parents[1] / "var" / "PAUSED_BY_OWNER"
SUPERSEDED = Path(__file__).resolve().parents[1] / "docs" / "status" / "SUPERSEDED_INSTRUCTIONS.json"


def superseded_ids() -> set:
    try:
        return {k for k in json.loads(SUPERSEDED.read_text()) if not k.startswith("_")}
    except (OSError, ValueError):
        return set()


def reason() -> Optional[str]:
    """The active pause reason, or None. A flag that cites an instruction the owner has since cancelled (SUPERSEDED_INSTRUCTIONS.json) is stale: ignored."""
    try:
        text = FLAG.read_text().strip() or "PAUSED_BY_OWNER (no reason text)"
    except OSError:
        return None
    return None if any(i in text for i in superseded_ids()) else text
