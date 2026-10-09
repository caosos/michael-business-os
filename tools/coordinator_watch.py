"""Cheap, NON-LLM coordinator watchdog for Agent 01 (owner command: activate agent watchdogs).

    .venv/bin/python -I tools/coordinator_watch.py [--once] [--status] [--interval 120] [--no-wake] [--inbox-ref origin/liaison/aria-to-agent-01]

What it does every cycle (no model is ever called; only git, HTTP GET to public GitHub, local files and tmux):
  1. fetch origin; list the owner liaison inbox (`docs/messages/inbox/*.md`) and the coordinator's ACKs (`docs/messages/acks/<id>.md`);
  2. decide whether Agent 01 is NEEDED: an unacknowledged owner message, or lane-01 READY work, or the dispatcher is down with READY work;
  3. wake Agent 01 ONLY if needed AND Claude's own session registry says the session is `idle` (not busy), the quota guard allows a turn, and the
     per-message limits allow it (>= 10 min apart, <= 3 wakes); the wake is one line naming message ids, never message bodies;
  4. VERIFY: "delivered" (typed into the pane) -> "ingested" (the session went busy after the wake) -> "acknowledged" (the ack file appears on the
     coordinator branch). Delivery is never reported as acknowledgement; an unacknowledged wake becomes STALE and, after 3 tries, OWNER_ACTION;
  5. read-only probes of the other two coordinators (Desktop-Agent issue #3, CAOSCare issue #117) from public GitHub: last inbound, last ACK, unacked;
  6. write var/watchdog/status.json (+ chained receipts var/watchdog/receipts.jsonl) and, rate-limited, docs/status/COORDINATOR_HEALTH.json for the
     central panel's owner to read. It never edits another project, never posts to GitHub, never starts workers (tools/dispatcher.py does that).
Health vocabulary: HEALTHY DEGRADED STOPPED STALE UNVERIFIED OWNER_ACTION.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mbos.hashing import sha256_of  # noqa: E402

WD = ROOT / "var" / "watchdog"
INBOX_REF_DEFAULT = "origin/liaison/aria-to-agent-01"
COORD_BRANCH = "origin/research/agent-01-coordinator"
MIN_WAKE_GAP_S, MAX_WAKES, ACK_DEADLINE_S, INGEST_WAIT_S = 600, 3, 900, 90
PROBES = {"desktop_agent": ("caosos/Desktop-Agent", 3), "caoscare": ("caosos/CAOSCARE.COM", 117)}
PANEL = "http://127.0.0.1:8477"


def now() -> float:
    return time.time()


def iso(t: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if t else None


# ------------------------------------------------------------------ pure decision logic (unit-tested)
def unacked(inbox_ids: list[str], ack_ids: set[str]) -> list[str]:
    return [i for i in inbox_ids if i not in ack_ids]


def wake_decision(*, needed: list[str], session: Optional[dict], quota_ok: bool, per_msg: dict, t: float) -> tuple[bool, str]:
    """Pure: (wake?, why). `per_msg` = {id: {"wakes": n, "last_wake": ts}}."""
    if not needed:
        return False, "nothing needed"
    if session is None:
        return False, "no live Claude session (awaiting connection)"
    if session.get("status") != "idle":
        return False, f"session is {session.get('status')!r}, not idle (it will see the work on its own sync)"
    if not quota_ok:
        return False, "quota guard: a wake costs a turn"
    eligible = [i for i in needed if per_msg.get(i, {}).get("wakes", 0) < MAX_WAKES
                and t - per_msg.get(i, {}).get("last_wake", 0) >= MIN_WAKE_GAP_S]
    if not eligible:
        return False, "wake limits reached or too soon (>=10 min apart, <=3 wakes per item)"
    return True, "wake for " + ", ".join(eligible)


def classify(*, session: Optional[dict], unacked_ids: list[str], per_msg: dict, last_check: Optional[float], t: float, quota_ok: bool = True) -> str:
    """HEALTHY DEGRADED STOPPED STALE UNVERIFIED OWNER_ACTION for the MBOS coordinator."""
    if last_check is None or t - last_check > 900:
        return "STALE"
    if any(per_msg.get(i, {}).get("wakes", 0) >= MAX_WAKES for i in unacked_ids):
        return "OWNER_ACTION"
    if session is None:
        return "STOPPED"
    if unacked_ids:
        return "DEGRADED"
    if not quota_ok:
        return "DEGRADED"
    return "HEALTHY"


def dispatcher_action(*, ready: int, alive: bool, quota_ok: bool, last_start: float, t: float) -> str:
    """Pure. NONE (nothing to do, or it is running), START (down while approved READY work waits), WAIT (quota or restarted <10 min ago)."""
    if alive or ready <= 0:
        return "NONE"
    if not quota_ok or t - last_start < 600:
        return "WAIT"
    return "START"


def stalled_workers(ps_lines: list[str], limit_s: int = 3900) -> list[dict]:
    """Pure. `etimes args` lines of bounded workers older than their own 3500 s timeout plus margin."""
    out = []
    for ln in ps_lines:
        parts = ln.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit() and "tools/worker.py" in parts[1] and "dispatcher.py" not in parts[1]:
            if int(parts[0]) > limit_s:
                toks = parts[1].split()
                out.append({"age_s": int(parts[0]), "task": toks[toks.index("tools/worker.py") + 1] if "tools/worker.py" in toks else "?"})
    return out


def ready_rows() -> int:
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import foreman
        report, _ = foreman.survey(ROOT)
        return sum(len(r["ready"]) for r in report if r["lane"] != "01")
    except Exception:  # noqa: BLE001
        return 0


def dispatcher_alive() -> bool:
    return subprocess.run(["tmux", "has-session", "-t", "mbos-dispatcher"], capture_output=True).returncode == 0


def start_dispatcher() -> bool:
    cmd = f"cd {ROOT} && exec .venv/bin/python -I tools/dispatcher.py 2>&1 | tee -a var/dispatcher.out"
    return subprocess.run(["tmux", "new-session", "-d", "-s", "mbos-dispatcher", cmd], capture_output=True).returncode == 0


def verify_wake(rec: dict, session: Optional[dict], acked: bool, t: float) -> str:
    """State of one wake: DELIVERED -> INGESTED -> ACKNOWLEDGED, or STALE. Delivery is never an acknowledgement."""
    if acked:
        return "ACKNOWLEDGED"
    ingested = bool(session and (session.get("status") == "busy" or (session.get("updatedAt") or 0) / 1000 > rec["at"] + 1))
    if ingested:
        return "INGESTED" if t - rec["at"] <= ACK_DEADLINE_S else "STALE"
    return "DELIVERED" if t - rec["at"] <= INGEST_WAIT_S else "STALE"


# ------------------------------------------------------------------ IO
def git(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)


def list_ids(ref: str, path: str) -> Optional[list[str]]:
    r = git("ls-tree", "-r", "--name-only", ref, path)
    if r.returncode:
        return None
    return sorted(Path(p).stem for p in r.stdout.splitlines() if p.endswith(".md"))


def my_session() -> Optional[dict]:
    best = None
    for p in glob.glob(os.path.expanduser("~/.claude/sessions/*.json")):
        try:
            d = json.load(open(p))
        except (OSError, ValueError):
            continue
        pid, cwd = d.get("pid"), d.get("cwd") or ""
        if pid and cwd.startswith(str(ROOT)) and os.path.exists(f"/proc/{pid}") and d.get("entrypoint") != "sdk":
            if best is None or (d.get("updatedAt") or 0) > (best.get("updatedAt") or 0):
                best = {k: d.get(k) for k in ("name", "pid", "status", "updatedAt", "tmux")}
    return best


def send_wake(session: dict, text: str) -> bool:
    """Types one line into the coordinator's tmux pane. DISABLED unless MBOS_ALLOW_TMUX_WAKE=1: the permission classifier denied agent self-driving
    through tmux (2026-10-09), so this needs explicit owner approval. The sanctioned wake path is the central bridge's Claude peer-message relay."""
    if os.environ.get("MBOS_ALLOW_TMUX_WAKE") != "1":
        return False
    target = (session.get("tmux") or "").split(".")[-1] or None   # pane id, e.g. %0
    if not target:
        return False
    a = subprocess.run(["tmux", "send-keys", "-t", target, "-l", text], capture_output=True)
    b = subprocess.run(["tmux", "send-keys", "-t", target, "Enter"], capture_output=True)
    return a.returncode == 0 and b.returncode == 0


def http_json(url: str, timeout: int = 10) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "mbos-coordinator-watch"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def probe_issue(repo: str, issue: int) -> dict:
    """Read-only: last inbound owner comment vs last coordinator/control-plane ACK on a public issue."""
    try:
        cs = http_json(f"https://api.github.com/repos/{repo}/issues/{issue}/comments?per_page=100&sort=created&direction=desc")
    except Exception as e:  # noqa: BLE001
        return {"state": "UNVERIFIED", "why": f"GitHub read failed: {type(e).__name__}"}
    import re
    ack_re = re.compile(r"\b(ACK|ACKNOWLEDGED|WORKING|BLOCKED|DONE|VERIFIED|DELIVERED)\b", re.I)
    inbound = [c for c in cs if not ack_re.match((c.get("body") or "").lstrip()[:20])]
    acks = [c for c in cs if ack_re.match((c.get("body") or "").lstrip()[:20])]
    li = max((c["created_at"] for c in inbound), default=None)
    la = max((c["created_at"] for c in acks), default=None)
    return {"repo": repo, "issue": issue, "last_inbound_at": li, "last_ack_at": la, "comments_read": len(cs),
            "ack_after_inbound": bool(li and la and la >= li)}


def quota_ok() -> bool:
    try:
        from mbos import router, telemetry
        return telemetry.quota_guard(router.load_policy())["allow"]
    except Exception:  # noqa: BLE001
        return True


def receipt(kind: str, detail: dict, sources: list[str]) -> None:
    WD.mkdir(parents=True, exist_ok=True)
    p = WD / "receipts.jsonl"
    prev = "sha256:" + "0" * 64
    if p.exists() and p.stat().st_size:
        prev = json.loads(p.read_text().splitlines()[-1])["row_hash"]
    row = {"at": iso(now()), "kind": kind, "detail": detail, "provenance": {"tool": "tools/coordinator_watch.py", "sources": sources}, "prev_hash": prev}
    row["row_hash"] = sha256_of({k: v for k, v in row.items() if k != "row_hash"})
    with p.open("a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def load_state() -> dict:
    p = WD / "state.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {"per_msg": {}, "wakes": [], "last_check": None, "last_probe": 0, "probes": {}, "published": {"at": 0, "digest": None}}


def save_state(s: dict) -> None:
    WD.mkdir(parents=True, exist_ok=True)
    (WD / "state.json").write_text(json.dumps(s, indent=1, sort_keys=True))


def probe_verdict(inbox_refs=None) -> dict:
    """Side-effect-free (reads only): the same question the daemon asks, as the central bridge's heartbeat contract:
    {"verdict": "WAKE"|"IDLE", "reasons": [...]}. WAKE only when Agent 01 has something safe to read."""
    refs = inbox_refs or [INBOX_REF_DEFAULT]
    git("fetch", "-q", "origin")
    ids = sorted({i for r in refs for i in (list_ids(r, "docs/messages/inbox") or [])})
    acks = set(list_ids(COORD_BRANCH, "docs/messages/acks") or []) | {p.stem for p in (ROOT / "docs" / "messages" / "acks").glob("*.md")}
    reasons = [f"unacknowledged owner message {i}" for i in unacked(ids, acks)]
    lane01 = 0
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import foreman
        q = foreman.show(ROOT, "research/agent-01-coordinator", "docs/status/READY_QUEUE.md") or ""
        lane01 = sum(1 for r in foreman.parse_queue(q) if r["status"].startswith("READY") and r["agent"].strip() in ("01", "01 (spine)", "01 (spine side)"))
    except Exception:  # noqa: BLE001
        pass
    if lane01:
        reasons.append(f"{lane01} READY row(s) owned by Agent 01")
    ps = subprocess.run(["ps", "-eo", "etimes,args"], capture_output=True, text=True).stdout.splitlines()
    reasons += [f"stalled worker {w['task']} ({w['age_s']} s)" for w in stalled_workers(ps)]
    return {"verdict": "WAKE" if reasons else "IDLE", "reasons": reasons}


def cycle(inbox_refs, do_wake: bool, probe: bool = True) -> dict:
    inbox_refs = [inbox_refs] if isinstance(inbox_refs, str) else list(inbox_refs)
    inbox_ref = ",".join(inbox_refs)
    t = now()
    st = load_state()
    git("fetch", "-q", "origin")
    lists = [list_ids(r, "docs/messages/inbox") for r in inbox_refs]
    inbox = None if all(x is None for x in lists) else sorted({i for x in lists if x for i in x})
    acks = set(list_ids(COORD_BRANCH, "docs/messages/acks") or [])
    local_acks = {p.stem for p in (ROOT / "docs" / "messages" / "acks").glob("*.md")}   # own worktree, written before push
    need = unacked(inbox or [], acks | local_acks) if inbox is not None else []
    head = git("rev-parse", "--short", COORD_BRANCH).stdout.strip()
    sess, q = my_session(), quota_ok()
    # verify earlier wakes
    for w in st["wakes"]:
        if w.get("state") in ("ACKNOWLEDGED",):
            continue
        done = all(i in (acks | local_acks) for i in w["ids"])
        new = verify_wake(w, sess, done, t)
        if new != w.get("state"):
            w["state"] = new
            w[new.lower() + "_at"] = t
            receipt(f"wake_{new.lower()}", {"ids": w["ids"], "wake_at": iso(w["at"])},
                    [f"{inbox_ref}:docs/messages/inbox", f"{COORD_BRANCH}@{head}:docs/messages/acks", "~/.claude/sessions registry"])
    for i in need:
        st["per_msg"].setdefault(i, {"first_seen": t, "wakes": 0})
    try:  # a central bridge that takes over waking sets {"wake": false}; this daemon then only checks, verifies and reports
        do_wake = do_wake and json.loads((WD / "mode.json").read_text()).get("wake", True)
    except (OSError, ValueError):
        pass
    ok, why = wake_decision(needed=need, session=sess, quota_ok=q, per_msg=st["per_msg"], t=t)
    woke = False
    if ok and do_wake:
        ids = [i for i in need if st["per_msg"][i]["wakes"] < MAX_WAKES and t - st["per_msg"][i].get("last_wake", 0) >= MIN_WAKE_GAP_S]
        text = ("WATCHDOG WAKE: unacknowledged owner message(s) in " + inbox_ref + ": " + ", ".join(ids) +
                ". Run the inbox loop in docs/COORDINATION.md (read, reconcile, write docs/messages/acks/<id>.md, push). No live actions.")
        if send_wake(sess, text):
            woke = True
            for i in ids:
                st["per_msg"][i]["wakes"] += 1
                st["per_msg"][i]["last_wake"] = t
            st["wakes"].append({"ids": ids, "at": t, "state": "DELIVERED", "delivered_at": t})
            receipt("wake_delivered", {"ids": ids, "session": sess.get("name"), "pane": sess.get("tmux")}, [f"{inbox_ref}:docs/messages/inbox"])
        else:
            why = "tmux wake is disabled (needs owner approval: MBOS_ALLOW_TMUX_WAKE=1); the central bridge's peer relay is the sanctioned wake"
    elif ok and not do_wake:
        why = "would wake (--no-wake)"
    # approved work waiting while the dispatcher is down; stalled workers
    ready = ready_rows()
    alive = dispatcher_alive()
    act = dispatcher_action(ready=ready, alive=alive, quota_ok=q, last_start=st.get("dispatcher_started", 0), t=t)
    if act == "START" and do_wake and start_dispatcher():
        st["dispatcher_started"] = t
        receipt("dispatcher_restarted", {"ready_rows": ready}, ["tools/foreman.py survey of origin READY_QUEUE", "tmux has-session mbos-dispatcher"])
    ps = subprocess.run(["ps", "-eo", "etimes,args"], capture_output=True, text=True).stdout.splitlines()
    stalled = stalled_workers(ps)
    for w in stalled:
        key = f"stalled:{w['task']}"
        if not st["per_msg"].get(key):
            st["per_msg"][key] = {"first_seen": t, "wakes": 0, "informational": True}
            receipt("worker_stalled", w, ["ps -eo etimes,args"])
    extras = {"approved_ready_rows_for_specialist_lanes": ready, "dispatcher_running": alive, "dispatcher_action": act, "stalled_workers": stalled}
    st["extras"] = extras
    st["last_check"] = t
    if probe and t - st.get("last_probe", 0) > 600:
        st["probes"] = {k: probe_issue(*v) for k, v in PROBES.items()}
        st["last_probe"] = t
    status = classify(session=sess, unacked_ids=need, per_msg=st["per_msg"], last_check=st["last_check"], t=t, quota_ok=q)
    if status == "HEALTHY" and st.get("extras", {}).get("stalled_workers"):
        status = "DEGRADED"
    out = status_doc(st, status, sess, need, why, woke, head, q, inbox_ref, inbox is not None)
    save_state(st)
    WD.mkdir(parents=True, exist_ok=True)
    (WD / "status.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    return out


def panel_health() -> dict:
    try:
        d = json.load(urllib.request.urlopen(PANEL + "/v0/health", timeout=5))
        return {"reachable": True, "ok": bool(d.get("ok")), "uptime_sec": d.get("uptime_sec")}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "why": type(e).__name__}


def status_doc(st: dict, status: str, sess: Optional[dict], need: list[str], why: str, woke: bool, head: str, q: bool, inbox_ref: str, inbox_ok: bool) -> dict:
    last_w = st["wakes"][-1] if st["wakes"] else None
    mbos = {"coordinator": "michael_business_os / Agent 01", "state": status, "last_check": iso(st["last_check"]),
            "last_wake": iso(last_w["at"]) if last_w else None, "last_wake_state": last_w["state"] if last_w else None,
            "last_acknowledged_wake": iso(max((w.get("acknowledged_at", 0) for w in st["wakes"]), default=0) or None),
            "session": sess, "unacknowledged_messages": need, "decision": why, "quota_allows_a_turn": q, "coordinator_head": head,
            "inbox": {"ref": inbox_ref, "readable": inbox_ok}, "work": st.get("extras", {}), "mechanism": "tools/coordinator_watch.py (no LLM) + Claude session registry + tmux wake"}
    others = {}
    for k, p in st.get("probes", {}).items():
        state = p.get("state") or ("HEALTHY" if p.get("ack_after_inbound") else "DEGRADED")
        others[k] = {**p, "state": state, "coordinator_session": "UNKNOWN (another account/host namespace; not readable from here)",
                     "note": "read-only public-GitHub probe; delivery to a live Claude session is the Desktop-Agent control plane's job"}
    return {"generated_at": iso(now()), "schema": "mbos.coordinator_health/1", "projects": {"michael_business_os": mbos, **others},
            "panel": {"url": PANEL, **panel_health(), "write_access": "none: the panel's write API needs a token this watchdog neither has nor seeks"}}


def publish(out: dict, st: dict) -> bool:
    """Rate-limited, change-driven status file on the coordinator branch for the central panel's owner to read."""
    t = now()
    digest = sha256_of({"m": {k: v for k, v in out["projects"]["michael_business_os"].items() if k not in ("last_check", "session")}})
    if t - st["published"]["at"] < 1800 and st["published"]["digest"] == digest:
        return False
    if t - st["published"]["at"] < 600:
        return False
    p = ROOT / "docs" / "status" / "COORDINATOR_HEALTH.json"
    p.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    st["published"] = {"at": t, "digest": digest}
    return True


def serve(port: int) -> None:
    """Read-only local feed for the central panel (same host, 127.0.0.1, GET /health.json, no auth needed because it carries no secrets and
    no write path). The panel's owner decides whether to render it; this watchdog never writes into the panel."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] not in ("/health.json", "/"):
                self.send_response(404); self.end_headers(); return
            f = WD / "status.json"
            body = f.read_bytes() if f.exists() else b'{"error":"no status yet"}'
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):  # silent
            pass

    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-wake", action="store_true")
    ap.add_argument("--interval", type=int, default=120)
    ap.add_argument("--serve-port", type=int, default=0, help="serve var/watchdog/status.json read-only on 127.0.0.1:PORT/health.json")
    ap.add_argument("--inbox-ref", action="append", help="repeatable; default the owner liaison inbox")
    a = ap.parse_args(argv)
    if a.status:
        print((WD / "status.json").read_text() if (WD / "status.json").exists() else "no status yet")
        return 0
    if a.serve_port:
        serve(a.serve_port)
    while True:
        out = cycle(a.inbox_ref or [INBOX_REF_DEFAULT], not a.no_wake)
        if a.once:
            print(json.dumps(out["projects"]["michael_business_os"], indent=1))
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
