"""Automatic pickup of authorized GitHub instructions for Agent 01 (no human sync). Runs under the `michaelos` account that owns the checkout.

    .venv/bin/python -I tools/inbox_pickup.py [--once] [--interval 60] [--status] [--dry]

Per cycle: fetch -> list the liaison inbox -> every NEW eligible id that has no ACK on the coordinator branch is picked up exactly once:
  FETCHED (seen) -> DELIVERED (executor started) -> ACKED (ack file pushed to the coordinator branch, deterministic, no model) -> RUNNING -> COMPLETED
  or BLOCKED with the specific reason (quota guard, missing claude CLI, dirty side worktree, executor failed, ack missing, non-doc files touched).
Executors: `Type: PING` messages are answered deterministically (zero tokens: a receipt echoing the nonce). Anything else runs ONE bounded
`claude -p` through tools/worker.py (same router, quota guard, deny-list and telemetry as every worker) in a SIDE worktree, limited to docs/ files;
real implementation is still queued in READY_QUEUE and run by tools/dispatcher.py. Nothing here contacts anyone, spends, bids or deploys.
Idempotency: state.json + the ack file. A restart never re-executes a COMPLETED or ACKED id; a RUNNING id whose process died is retried (max 3).
Heartbeat: var/pickup/heartbeat.json and, on change or every 10 min, `status/agent-01-pickup:PICKUP_HEALTH.json` on GitHub.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickup_git as pg  # noqa: E402
from pickup_state import Store, now, summary  # noqa: E402

ROOT = pg.ROOT
DIR = Path(os.environ.get("MBOS_PICKUP_DIR", str(ROOT / "var" / "pickup")))
ID_RE = re.compile(r"^(ARIA|ARYA|DA)-(\d{8})-(\d{4})-")
SENDERS = ("ARIA", "ARYA", "DA")
CUTOFF = os.environ.get("MBOS_PICKUP_AFTER", "20261010-0000")     # older ids are history, never auto-executed
MAX_ATTEMPTS, RETRY_S, HEARTBEAT_S = 3, 600, 600


def eligible(mid: str, cutoff: str = CUTOFF) -> bool:
    m = ID_RE.match(mid)
    return bool(m) and m.group(1) in SENDERS and f"{m.group(2)}-{m.group(3)}" >= cutoff


def is_ping(body: str) -> Optional[str]:
    m = re.search(r"^Type:\s*PING\b.*$", body, re.M)
    n = re.search(r"^Nonce:\s*([A-Za-z0-9_.:-]{1,64})\s*$", body, re.M)
    return (n.group(1) if n else "none") if m else None


def pending(inbox: list[str], acked: set[str], data: dict[str, Any], t: float, cutoff: str = CUTOFF) -> list[str]:
    out = []
    for mid in inbox:
        r = data.get(mid, {})
        if not eligible(mid, cutoff) or r.get("state") == "COMPLETED":
            continue
        if mid in acked and r.get("state") in ("ACKED", "RUNNING", "COMPLETED"):
            continue                                                  # already acknowledged: never executed twice
        if r.get("state") == "RUNNING":
            continue                                                  # recover() decides
        if r.get("attempts", 0) >= MAX_ATTEMPTS or (r.get("retry_after") or 0) > t:
            continue
        out.append(mid)
    return out


def recover(store: Store, acked: set[str], alive) -> list[str]:
    """After a restart: a RUNNING id with no live executor is COMPLETED if its ack and receipt exist, else retried (counted)."""
    fixed = []
    for mid, r in store.all().items():
        if r.get("state") != "RUNNING" or alive(r.get("pid")):
            continue
        if mid in acked and r.get("receipt_file_pushed"):
            store.move(mid, "COMPLETED", operation="recovered", outcome="executor gone, ack and receipt present")
        else:
            store.block(mid, "executor process died before finishing (will retry)", retry_after=time.time(), attempts=r.get("attempts", 0))
        fixed.append(mid)
    return fixed


def alive(pid: Optional[int]) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, OSError):
        return False


def ack_text(mid: str, stage: str, extra: str = "") -> str:
    return (f"# ACK: {mid}\n\n- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/{mid}.md`\n- **Stage:** {stage}\n"
            f"- **Acked by:** automatic pickup (Agent 01, `tools/inbox_pickup.py`) at {now()}; no human relay.\n"
            f"- **Safety:** dry-run; no bid, purchase, seller contact, spend, deploy, restart or change to other projects.\n{extra}")


def write_file(wt: Path, rel: str, text: str) -> None:
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def work_prompt(mid: str, body_ref: str) -> str:
    return f"""You are Agent 01's automatic inbox executor for Michael Business OS (bounded, no chat context; repo truth is your memory).
Instruction id: {mid}. Read it with `git show {body_ref}:docs/messages/inbox/{mid}.md`; read START_HERE.md and docs/COORDINATION.md on origin/research/agent-01-coordinator.
The ACK file docs/messages/acks/{mid}.md already exists: if its Stage says COMPLETED, stop. Otherwise:
1. Do what the instruction asks ONLY as routine coordination: read, verify, reconcile docs/status/READY_QUEUE.md rows, write receipts under docs/receipts/. You may edit files under docs/ ONLY.
2. Anything that needs code, a live restart, spending, bids, contact, or other projects: do NOT do it; add a READY_QUEUE row for the right lane or state the exact owner decision needed.
3. Write docs/receipts/pickup/{mid}.md (what you did, evidence links, tests with numbers, remaining blockers) and replace the ack's Stage line with `COMPLETED` or `BLOCKED: <reason>`.
4. `git add docs`, commit, `git push origin HEAD`. Print a final JSON line {{"task":"{mid}","status":"DONE|BLOCKED","commit":"<sha>","notes":"<one line>"}}.
Hard rules: dry-run only; never touch other branches or projects; no secrets in files."""


def run_work(mid: str, wt: Path, dry: bool) -> dict[str, Any]:
    import worker  # noqa: E402
    from mbos import router
    row = f"| {mid} | P0 | automatic inbox execution | none | READY | 01 | receipt docs/receipts/pickup/{mid}.md |"
    prof = router.TaskProfile(task_id=mid, lane="01", kind="implement", risk="medium", cross_lane=False, long_horizon=False)
    return worker.run_one(mid, "01", prof, worktree=wt, dry=dry, model=None, escalate=False, branch_override=pg.SIDE_BRANCH, max_turns=40,
                          skip_session_check=True, queue_text=row, timeout_s=1500, prompt_override=work_prompt(mid, pg.INBOX_REF))


def deliver(mid: str, store: Store, dry: bool, executor=run_work) -> str:
    """One pickup, start to finish. Returns the final state name."""
    body = pg.read_message(mid)
    attempts = store.get(mid).get("attempts", 0) + 1
    if body is None:
        store.block(mid, "message file unreadable on the liaison branch", attempts=attempts, retry_after=time.time() + RETRY_S)
        return "BLOCKED"
    if not store.get(mid):
        store.move(mid, "FETCHED", operation="fetched", evidence=[f"{pg.INBOX_REF}:docs/messages/inbox/{mid}.md"], attempts=0)
    ping = is_ping(body)
    if ping is None and not shutil.which("claude"):
        store.block(mid, "delivery interface missing: `claude` CLI not found for the account running the watcher", attempts=attempts, retry_after=time.time() + RETRY_S)
        return "BLOCKED"
    wt, why = pg.prepare_side()
    if wt is None:
        store.block(mid, why, attempts=attempts, retry_after=time.time() + RETRY_S)
        return "BLOCKED"
    store.move(mid, "DELIVERED", operation="executor started", attempts=attempts, pid=os.getpid(), kind="PING" if ping is not None else "WORK")
    if mid not in pg.acked_ids():                                         # a retry never re-acks
        write_file(wt, f"docs/messages/acks/{mid}.md", ack_text(mid, "ACKED (received and queued by automatic pickup; NOT yet completed)"))
        sha = pg.commit_all(wt, f"agent 01 pickup: ACK {mid}")
        ok, detail = pg.publish(wt) if sha else (False, "nothing to commit")
        if not ok:
            store.block(mid, "ack not published: " + detail, attempts=attempts, retry_after=time.time() + RETRY_S)
            return "BLOCKED"
        store.move(mid, "ACKED", operation="ack pushed", evidence=[f"origin/{pg.COORD}:docs/messages/acks/{mid}.md"], branch=pg.COORD, sha=detail)
    store.move(mid, "RUNNING", operation="execute", pid=os.getpid())
    if ping is not None:
        write_file(wt, f"docs/receipts/pickup/{mid}.md", f"# Pickup receipt: {mid}\n\n- Operation: PING echo (deterministic, zero model tokens)\n- Nonce echoed: `{ping}`\n"
                   f"- Executed at {now()} on host `{socket.gethostname()}` by account `{os.environ.get('USER', '?')}`; coordinator head `{pg.head()}`.\n")
        write_file(wt, f"docs/messages/acks/{mid}.md", ack_text(mid, "COMPLETED (PING answered)", f"- **Receipt:** `docs/receipts/pickup/{mid}.md`\n"))
        pg.commit_all(wt, f"agent 01 pickup: COMPLETED {mid}")
        outcome, code = "ping answered", 0
    else:
        res = executor(mid, wt, dry)
        pg.commit_all(wt, f"agent 01 pickup: executor changes for {mid}")
        bad = [f for f in pg.changed_files(wt) if not f.startswith("docs/")]
        if bad:
            store.block(mid, "executor touched non-docs files, not published: " + ", ".join(bad[:4]), attempts=attempts, exit_status=2)
            return "BLOCKED"
        outcome, code = ("executor finished" if res.get("ok") else "executor did not complete: " + str(res.get("error") or res.get("worker_report"))[:160]), (0 if res.get("ok") else 1)
        if not res.get("ok") and not res.get("process_ok"):
            store.block(mid, outcome, attempts=attempts, exit_status=code, retry_after=time.time() + RETRY_S)
            return "BLOCKED"
    ok, detail = pg.publish(wt)
    if not ok:
        store.block(mid, "receipt not published: " + detail, attempts=attempts, exit_status=code)
        return "BLOCKED"
    store.move(mid, "COMPLETED", operation="completed", outcome=outcome, exit_status=code, receipt_file_pushed=True, branch=pg.COORD, sha=detail,
               evidence=[f"origin/{pg.COORD}:docs/receipts/pickup/{mid}.md"])
    return "COMPLETED"


def build_heartbeat(store: Store, git_ok: bool, interval: int, started: str, busy: Optional[str]) -> dict[str, Any]:
    data = store.all()
    try:
        wd = json.loads((ROOT / "var" / "watchdog" / "status.json").read_text())["projects"]["michael_business_os"]
    except (OSError, ValueError, KeyError):
        wd = {}
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from mbos import router, telemetry
        g = telemetry.quota_guard(router.load_policy())
    except Exception as e:  # noqa: BLE001
        g = {"allow": None, "reason": f"quota reading unavailable: {e}"}
    blockers = [{"id": k, "reason": v.get("blocked"), "attempts": v.get("attempts"), "since": v.get("blocked_at")} for k, v in data.items() if v.get("state") == "BLOCKED"]
    if not git_ok:
        blockers.append({"id": "-", "reason": "git fetch failed: no network or no GitHub access for this account", "since": now()})
    return {"schema": "mbos.pickup_health/1", "generated_at": now(), "host": socket.gethostname(), "account": os.environ.get("USER", "?"), "pid": os.getpid(),
            "watcher": {"status": "running" if git_ok else "DEGRADED", "interval_s": interval, "started_at": started, "inbox_ref": pg.INBOX_REF, "ack_branch": pg.COORD,
                        "eligible_ids": "ARIA|ARYA|DA-YYYYMMDD-HHMM-* at or after " + CUTOFF},
            "session": {"name": "mbos-pickup", "status": "busy" if busy else "idle", "pid": os.getpid(), "observed_at": now(), "source": "inbox_pickup process", "ttl_sec": 300},
            "interactive_coordinator": {"state": wd.get("state", "UNKNOWN"), "decision": wd.get("decision"), "note": "pickup does not need the interactive session"},
            "delivery_interface": {"claude_cli": bool(shutil.which("claude")), "quota_allows_a_run": g.get("allow"), "quota": g.get("reason"), "side_worktree": str(pg.SIDE)},
            "counts": summary(data), "blockers": blockers, "currently_running": busy, "coordinator_head": pg.head(),
            "receipts": "var/pickup/receipts.jsonl (hash-chained, local) and docs/receipts/pickup/<id>.md on the coordinator branch"}


def cycle(store: Store, dry: bool, hb_state: dict, interval: int, started: str) -> dict[str, Any]:
    git_ok = pg.fetch()
    busy = None
    if git_ok:
        inbox, acked = pg.inbox_ids(), pg.acked_ids()
        for mid in inbox:
            if eligible(mid) and not store.get(mid) and mid not in acked:
                store.move(mid, "FETCHED", operation="fetched", evidence=[f"{pg.INBOX_REF}:docs/messages/inbox/{mid}.md"], attempts=0)
        recover(store, acked, alive)
        for mid in pending(inbox, acked, store.all(), time.time())[:2]:
            busy = mid
            deliver(mid, store, dry)
            busy = None
    hb = build_heartbeat(store, git_ok, interval, started, busy)
    text = json.dumps(hb, indent=1, sort_keys=True)
    (DIR / "heartbeat.json").write_text(text)
    key = json.dumps({k: hb[k] for k in ("counts", "blockers", "watcher")}, sort_keys=True)
    if git_ok and (key != hb_state.get("key") or time.time() - hb_state.get("at", 0) > HEARTBEAT_S):
        ok, detail = pg.publish_heartbeat(text)
        hb_state.update(key=key, at=time.time(), published=ok, detail=detail)
        store.receipt("heartbeat", "publish heartbeat", "ok" if ok else "failed: " + detail, evidence=[f"origin/{pg.STATUS_BRANCH}:PICKUP_HEALTH.json"], branch=pg.STATUS_BRANCH, sha=detail if ok else None)
    return hb


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry", action="store_true", help="plan WORK executors without launching claude")
    a = ap.parse_args(argv)
    DIR.mkdir(parents=True, exist_ok=True)
    store = Store(DIR)
    if a.status:
        print(json.dumps({"summary": summary(store.all()), "heartbeat_file": str(DIR / "heartbeat.json")}, indent=1))
        return 0
    lock = open(DIR / "lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another inbox_pickup is already running (lock held)", file=sys.stderr)
        return 3
    started, hb_state = now(), {}
    store.receipt("watcher", "watcher started", "ok", evidence=[f"pid {os.getpid()}"])
    while True:
        try:
            hb = cycle(store, a.dry, hb_state, a.interval, started)
            print(f"{now()} cycle ok: {hb['counts']} blockers={len(hb['blockers'])}", flush=True)
        except Exception as e:  # noqa: BLE001  (a bad cycle must not kill the watcher; it is recorded and visible)
            store.receipt("watcher", "cycle error", f"{type(e).__name__}: {str(e)[:160]}", exit_status=1)
            print(f"{now()} cycle error {e}", file=sys.stderr, flush=True)
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
