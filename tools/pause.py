"""Owner pause switch for Deal Sniffer / MBOS MODEL work. If `var/PAUSED_BY_OWNER` exists, nothing may start a model job:
tools/dispatcher.py exits, tools/worker.py refuses to launch, and tools/inbox_pickup.py will not run a WORK executor (zero-model PING and
heartbeat still work). Resume = delete the file (see docs/status/PAUSED_BY_OWNER.md)."""
from pathlib import Path
from typing import Optional

FLAG = Path(__file__).resolve().parents[1] / "var" / "PAUSED_BY_OWNER"


def reason() -> Optional[str]:
    try:
        return FLAG.read_text().strip() or "PAUSED_BY_OWNER (no reason text)"
    except OSError:
        return None
