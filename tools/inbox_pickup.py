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
import pickup_health as ph  # noqa: E402
import pause  # noqa: E402
from pickup_state import Store, now, summary  # noqa: E402

ROOT = pg.ROOT
DIR = Path(os.environ.get("MBOS_PICKUP_DIR", str(ROOT / "var" / "pickup")))
ID_RE = re.compile(r"^(ARIA|ARYA|DA)-(\d{8})-(\d{4})-")
SENDERS = ("ARIA", "ARYA", "DA")
CUTOFF = os.environ.get("MBOS_PICKUP_AFTER", "20261010-0000")     # older ids are history, never auto-executed
MAX_ATTEMPTS, RETRY_S, HEARTBEAT_S = 3, 600, 600


def eligible(mid: str, cutoff: str = CUTOFF) -> bool:
    m = ID_RE.match(mid)
    return bool(m) and m.group(1) in SENDERS and f"{m.group(2)}-{m.group(3)}" >= cutoff and mid not in pause.superseded_ids()


def is_ping(body: str) -> Optional[str]:
    m = re.search(r"^Type:\s*PING\b.*$", body, re.M)
    n = re.search(r"^Nonce:\s*([A-Za-z0-9_.:-]{1,64})\s*$", body, re.M)
    return (n.group(1) if n else "none") if m else None


def is_engineering(body: str) -> bool:
    """`Type: ENGINEERING_PROOF`: must be executed by the interactive engineering session (A-63). Pickup only ACKs it and leaves it open."""
    return bool(re.search(r"^Type:\s*ENGINEERING_PROOF\b", body, re.M))


def reconcile_engineering(store: Store) -> list[str]:
    """An engineering-owned message pickup left open becomes COMPLETED when the engineering session set its ack Stage to COMPLETED on origin."""
    done = []
    for mid, r in store.all().items():
        if r.get("state") != "BLOCKED" or "engineering" not in str(r.get("needs", "")):
            continue
        ack = pg.git("show", f"origin/{pg.COORD}:docs/messages/acks/{mid}.md").stdout
        if re.search(r"\*\*Stage:\*\*\s*COMPLETED\b", ack):
            store.correct(mid, "COMPLETED", "the interactive engineering session completed it (ack Stage COMPLETED on origin)", evidence=[f"origin/{pg.COORD}:docs/messages/acks/{mid}.md"])
            done.append(mid)
    return done


def pending(inbox: list[str], acked: set[str], data: dict[str, Any], t: float, cutoff: str = CUTOFF) -> list[str]:
    out = []
    for mid in inbox:
        r = data.get(mid, {})
        if not eligible(mid, cutoff) or r.get("state") == "COMPLETED":
            continue
        if mid in acked and (not r or r.get("state") in ("FETCHED", "ACKED", "RUNNING", "COMPLETED")):
            continue                  # acknowledged by anyone (a human, another run): never executed twice. Only our own BLOCKED retries pass
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
Hard rules: dry-run only; stay on the branch you are on (do not create, switch or reset branches, do not rebase; the watcher publishes for you); never touch other branches or projects; no secrets in files."""


def run_work(mid: str, wt: Path, dry: bool) -> dict[str, Any]:
    import worker  # noqa: E402
    from mbos import router
    row = f"| {mid} | P0 | automatic inbox execution | none | READY | 01 | receipt docs/receipts/pickup/{mid}.md |"
    prof = router.TaskProfile(task_id=mid, lane="01", kind="implement", risk="medium", cross_lane=False, long_horizon=False)
    return worker.run_one(mid, "01", prof, worktree=wt, dry=dry, model=None, escalate=False, branch_override=pg.SIDE_BRANCH, max_turns=40,
                          skip_session_check=True, queue_text=row, timeout_s=1500, prompt_override=work_prompt(mid, pg.INBOX_REF))


def ack_stage(wt: Path, mid: str) -> str:
    """The final stage the executor recorded in the ack file: COMPLETED | BLOCKED | ACKED | UNKNOWN. The heartbeat must follow this, not the exit code."""
    try:
        m = re.search(r"\*\*Stage:\*\*\s*(COMPLETED|BLOCKED|ACKED)\b([^\n]*)", (wt / f"docs/messages/acks/{mid}.md").read_text())
    except OSError:
        return "UNKNOWN"
    return m.group(1) + (":" + m.group(2).strip(" :")[:200] if m and m.group(1) == "BLOCKED" else "")


def deliver(mid: str, store: Store, dry: bool, executor=None) -> str:
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
        eng = is_engineering(body)
        write_file(wt, f"docs/messages/acks/{mid}.md", ack_text(mid, "ACKED (received by automatic pickup; AWAITING the interactive engineering session, which pickup does not replace; NOT completed)" if eng
                                                                else "ACKED (received and queued by automatic pickup; NOT yet completed)"))
        sha = pg.commit_all(wt, f"agent 01 pickup: ACK {mid}")
        ok, detail = pg.publish(wt) if sha else (False, "nothing to commit")
        if not ok:
            store.block(mid, "ack not published: " + detail, attempts=attempts, retry_after=time.time() + RETRY_S)
            return "BLOCKED"
        store.move(mid, "ACKED", operation="ack pushed", evidence=[f"origin/{pg.COORD}:docs/messages/acks/{mid}.md"], branch=pg.COORD, sha=detail)
    if is_engineering(body):                           # only the interactive engineering session may execute and complete it
        store.block(mid, "awaiting the interactive engineering session (pickup acked only, never executes or completes it)", attempts=max(attempts - 1, 0), retry_after=9e12,
                    needs="interactive engineering session", branch=pg.COORD)
        return "BLOCKED"
    if ping is None and pause.reason():                # owner pause: acknowledged, but no model executor may start
        store.block(mid, "PAUSED_BY_OWNER: model work disabled; acknowledged only (resume = delete var/PAUSED_BY_OWNER)", attempts=max(attempts - 1, 0),
                    retry_after=time.time() + 3600, needs="owner resume")
        return "BLOCKED"
    store.move(mid, "RUNNING", operation="execute", pid=os.getpid())
    if ping is not None:
        write_file(wt, f"docs/receipts/pickup/{mid}.md", f"# Pickup receipt: {mid}\n\n- Operation: PING echo (deterministic, zero model tokens)\n- Nonce echoed: `{ping}`\n"
                   f"- Executed at {now()} on host `{socket.gethostname()}` by account `{os.environ.get('USER', '?')}`; coordinator head `{pg.head()}`.\n")
        write_file(wt, f"docs/messages/acks/{mid}.md", ack_text(mid, "COMPLETED (PING answered)", f"- **Receipt:** `docs/receipts/pickup/{mid}.md`\n"))
        pg.commit_all(wt, f"agent 01 pickup: COMPLETED {mid}")
        outcome, code = "ping answered", 0
    else:
        res = (executor or run_work)(mid, wt, dry)
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
    stage = ack_stage(wt, mid)
    if not stage.startswith("COMPLETED"):          # the ack file is the truth: never report COMPLETED over a BLOCKED / unfinished ack
        why = stage.split(":", 1)[1] if stage.startswith("BLOCKED:") else ("executor left the ack at " + stage)
        store.block(mid, why or "executor reported BLOCKED", attempts=attempts, exit_status=code, retry_after=9e12, needs="interactive coordinator or owner (see the ack)",
                    branch=pg.COORD, sha=detail, evidence=[f"origin/{pg.COORD}:docs/messages/acks/{mid}.md"])
        return "BLOCKED"
    store.move(mid, "COMPLETED", operation="completed", outcome=outcome, exit_status=code, receipt_file_pushed=True, branch=pg.COORD, sha=detail,
               evidence=[f"origin/{pg.COORD}:docs/receipts/pickup/{mid}.md"])
    return "COMPLETED"


def cycle(store: Store, dry: bool, beat: "ph.Beat") -> dict[str, Any]:
    beat.git_ok = pg.fetch()
    if beat.git_ok:
        inbox, acked = pg.inbox_ids(), pg.acked_ids()
        for mid in inbox:
            if not eligible(mid) or store.get(mid):
                continue
            if mid in acked:   # handled by someone else before we saw it: record it, do not execute it
                store.move(mid, "COMPLETED", operation="skipped", outcome="already acknowledged by another actor; not executed by pickup", evidence=[f"origin/{pg.COORD}:docs/messages/acks/{mid}.md"])
            else:
                store.move(mid, "FETCHED", operation="fetched", evidence=[f"{pg.INBOX_REF}:docs/messages/inbox/{mid}.md"], attempts=0)
        recover(store, acked, alive)
        reconcile_engineering(store)
        for mid in pending(inbox, acked, store.all(), time.time())[:2]:
            beat.start_delivery(mid)                 # task id + start time are published BEFORE the long synchronous delivery
            try:
                deliver(mid, store, dry)
            finally:
                beat.end_delivery()                  # completion beat first, then currently_running is cleared
    return beat.beat()


def code_stamp() -> tuple:
    return tuple((f, (Path(__file__).parent / f).stat().st_mtime_ns) for f in ("inbox_pickup.py", "pickup_git.py", "pickup_state.py", "queue_guard.py"))


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
    started, stamp0 = now(), code_stamp()
    beat = ph.Beat(store, DIR, a.interval, started)
    beat.thread()                                    # keeps beating while a long delivery blocks the loop
    store.receipt("watcher", "watcher started", "ok", evidence=[f"pid {os.getpid()}"])
    while True:
        try:
            beat.cycle_ok = True
            hb = cycle(store, a.dry, beat)
            print(f"{now()} cycle ok: {hb['counts']} blockers={len(hb['blockers'])}", flush=True)
        except Exception as e:  # noqa: BLE001  (a bad cycle must not kill the watcher; it is recorded and visible)
            beat.cycle_ok = False
            store.receipt("watcher", "cycle error", f"{type(e).__name__}: {str(e)[:160]}", exit_status=1)
            print(f"{now()} cycle error {e}", file=sys.stderr, flush=True)
        if a.once:
            return 0
        time.sleep(a.interval)
        if code_stamp() != stamp0:                      # a fix was committed: re-exec this same process, never between instructions
            store.receipt("watcher", "code changed: re-exec", "ok")
            os.execv(sys.executable, [sys.executable, "-u", "-I", *sys.argv])


if __name__ == "__main__":
    sys.exit(main())
