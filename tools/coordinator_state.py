"""Michael Business OS coordinator state for Mission Control (:8477). Read-only, stdlib + local files, no LLM.

Prints one JSON object per the CAOSCare `coordinator_state.py` shape so the central panel can show every coordinator uniformly:
project, last_received, last_ack, open_items, heartbeat, event_wake / periodic_wake (VERIFIED | UNVERIFIED | STOPPED with evidence),
accepts_messages, scheduled_self_checks. Derived only from the watchdog's chained receipts and status; nothing is invented.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coordinator_watch as cw  # noqa: E402


def state() -> dict:
    rows = []
    p = cw.WD / "receipts.jsonl"
    if p.exists():
        rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    st = cw.load_state()
    wakes = st.get("wakes", [])
    acked = [w for w in wakes if w.get("state") == "ACKNOWLEDGED"]
    status = json.loads((cw.WD / "status.json").read_text()) if (cw.WD / "status.json").exists() else {}
    m = (status.get("projects") or {}).get("michael_business_os", {})
    ev = ("VERIFIED" if acked else ("UNVERIFIED" if wakes else "UNVERIFIED"))
    return {
        "project": "michael_business_os",
        "session_dir": str(cw.ROOT),
        "last_received": cw.iso(max((w["at"] for w in wakes), default=0) or None),
        "last_ack": cw.iso(max((w.get("acknowledged_at", 0) for w in acked), default=0) or None),
        "open_items": m.get("unacknowledged_messages", []),
        "heartbeat": cw.probe_verdict(),
        "event_wake": {"status": ev, "evidence": (
            "; ".join(f"{','.join(w['ids'])}: delivered {cw.iso(w['at'])} -> ACK {cw.iso(w.get('acknowledged_at'))}" for w in acked[-3:])
            or "no wake has been acknowledged yet (see var/watchdog/receipts.jsonl)")},
        "periodic_wake": {"status": "VERIFIED" if (cw.WD / "daemon.out").exists() and m.get("last_check") else "UNVERIFIED",
                          "evidence": f"tools/coordinator_watch.py checks every 120 s with no LLM (last check {m.get('last_check')}); it wakes the session only when the probe says WAKE"},
        "accepts_messages": bool(m.get("session")) and m["session"].get("status") in ("idle", "busy"),
        "scheduled_self_checks": "tools/coordinator_watch.py (tmux mbos-watchdog) every 120 s, no model call; restart after reboot is host-gated (O-1)",
        "health": m.get("state", "UNVERIFIED"),
        "receipts": len(rows),
    }


if __name__ == "__main__":
    print(json.dumps(state()))
