"""No-LLM heartbeat probe for the Michael Business OS coordinator (same contract as CAOSCare's heartbeat_probe.py).

Prints one JSON line {"verdict": "WAKE"|"IDLE", "reasons": [...]}. Read-only: it fetches origin and reads files; it never calls a model, never
posts, never types into a session. The central Desktop-Agent bridge may run it on its own schedule and send a peer message when it says WAKE;
tools/coordinator_watch.py (the local daemon) asks the same question and, until the bridge does, performs the bounded wake itself.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coordinator_watch  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(coordinator_watch.probe_verdict()))
