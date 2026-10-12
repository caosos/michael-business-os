"""A-71: ETA-driven checkpoints and the once-only event outbox, run INSIDE the existing local watchdog (tools/coordinator_watch.py).

Owner addenda (2026-10-11/12, liaison messages *eta-driven-checks*, *use-pr1-event-bridge*, *visible-claude-activity-updates*,
*event-driven-worker-wake*). No new coordinator, worker, queue, monitor or service: the watchdog calls `tick()` every cycle.

* Every ACK/WORKING checkpoint carries: project, task, responsible, stage, evidence, eta, next_check_at (exact America/Chicago),
  acceptance, blocker (or NONE). `validate()` refuses anything less, a vague ETA, or a timestamp that is not Chicago time.
* At a due next_check_at the watchdog publishes EXACTLY ONE outcome (`decide()`): DONE (a DONE record exists, also early),
  WORKING (the worker process is observed alive: new next_check_at), or NEED/BLOCKED (worker observed gone, or no host evidence:
  "APPEARS STALE — HOST STATE UNVERIFIED"). A missed check is recorded as an exception with provenance.
* Every meaningful event goes once to var/watchdog/events.jsonl with a stable event_id (dedupe, ordering by seq). Events from another
  project are quarantined, never relayed. The relay posts pending DealSniffer events, in order, to PR #1 as transport only; an event is
  marked posted only after a successful post (retry without duplicates). Relay output never becomes a new event (no loop).
* Owner-alert class follows addendum 7 (exceptions); the later DealSniffer directive also makes every meaningful event visible, so all
  events are relayed and `owner_alert` marks the exception ones.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

PROJECT = "DealSniffer"
CHICAGO = ZoneInfo("America/Chicago")
STAGES = ("DELIVERED", "ACK", "WORKING", "DONE", "NEED", "BLOCKED", "EXCEPTION", "DISPATCH")
OUTCOMES = ("WORKING", "DONE", "NEED")
REQUIRED = ("project", "task", "responsible", "stage", "evidence", "eta", "next_check_at", "acceptance", "blocker")
VAGUE_ETA = re.compile(r"^\s*(soon|tbd|asap|later|shortly|n/?a|unknown|\?+)\s*$", re.I)
OWNER_ALERT = {"NEED", "BLOCKED", "EXCEPTION"}
STALE = "APPEARS STALE — HOST STATE UNVERIFIED"
PR_REPO, PR_NUMBER = "caosos/michael-business-os", 1
REVISE_S = 30 * 60


def parse_chicago(s: str) -> Optional[datetime]:
    """'2026-10-11 23:52 CDT' / '... CST' / ISO with -05:00/-06:00 -> aware datetime in Chicago; anything else None."""
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?\s*(CDT|CST)", s)
    if m:
        dt = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}").replace(tzinfo=CHICAGO)
        return dt if dt.tzname() == m.group(3) else None            # 'CST' in daylight time is rejected, not silently shifted
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() != dt.astimezone(CHICAGO).utcoffset():
        return None
    return dt.astimezone(CHICAGO)


def fmt_chicago(dt: datetime) -> str:
    d = dt.astimezone(CHICAGO)
    return d.strftime("%Y-%m-%d %H:%M ") + d.tzname()


def validate(rec: dict) -> list[str]:
    errs = [f"missing {k}" for k in REQUIRED if not str(rec.get(k) or "").strip()]
    if rec.get("project") and rec["project"] != PROJECT:
        errs.append(f"project must be {PROJECT}")
    if rec.get("stage") and rec["stage"] not in STAGES:
        errs.append(f"unknown stage {rec['stage']}")
    if rec.get("eta") and VAGUE_ETA.match(str(rec["eta"])):
        errs.append("eta must come from the actual scope (not a generic estimate)")
    if rec.get("next_check_at") and parse_chicago(rec["next_check_at"]) is None:
        errs.append("next_check_at must be an exact America/Chicago timestamp (e.g. 2026-10-11 23:52 CDT)")
    return errs


def due(rec: dict, now: datetime) -> bool:
    t = parse_chicago(rec["next_check_at"])
    return t is not None and now >= t


def decide(rec: dict, *, now: datetime, done_ref: Optional[str], worker_alive: Optional[bool], observed_at: str) -> Optional[dict]:
    """Exactly one outcome when DONE exists (any time) or the check is due; None while not due. Never claims a stopped worker without evidence."""
    base = {"project": PROJECT, "task": rec["task"], "responsible": rec["responsible"], "host_observed_at": observed_at}
    if done_ref:
        return {**base, "stage": "DONE", "evidence": done_ref, "early": not due(rec, now)}
    if not due(rec, now):
        return None
    missed = f"next_check_at {rec['next_check_at']} reached without a DONE record"
    if worker_alive:
        nxt = fmt_chicago(now + timedelta(seconds=REVISE_S))
        return {**base, "stage": "WORKING", "evidence": f"worker process observed alive at {observed_at}; {missed}", "eta": f"revised: past {rec['eta']}",
                "next_check_at": nxt, "blocker": "NONE", "exception": "missed ETA"}
    if worker_alive is False:
        return {**base, "stage": "NEED", "evidence": f"no worker process for {rec['task']} at {observed_at}; {missed}",
                "blocker": "worker not running and no DONE record: re-dispatch or record the result", "exception": "missed check"}
    return {**base, "stage": "NEED", "evidence": f"{STALE}; {missed}", "blocker": STALE, "exception": "missed check"}


def event_id(ev: dict) -> str:
    key = "|".join(str(ev.get(k) or "") for k in ("project", "task", "stage", "receipt", "commit", "next_check_at", "evidence"))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class Outbox:
    """events.jsonl (append-only, ordered by seq), quarantine.jsonl, relay.json {posted: {event_id: ref}}."""

    def __init__(self, wd: Path):
        self.wd = Path(wd)
        self.events, self.quarantine, self.relay_state = self.wd / "events.jsonl", self.wd / "quarantine.jsonl", self.wd / "relay.json"

    def _rows(self) -> list[dict]:
        if not self.events.exists():
            return []
        return [json.loads(x) for x in self.events.read_text().splitlines() if x.strip()]

    def add(self, ev: dict, *, at: str) -> Optional[dict]:
        self.wd.mkdir(parents=True, exist_ok=True)
        if ev.get("project") != PROJECT:
            with self.quarantine.open("a") as f:
                f.write(json.dumps({**ev, "quarantined_at": at}, sort_keys=True) + "\n")
            return None
        if ev.get("source") == "relay":
            return None                                               # relay output never re-enters the outbox (no loop)
        rows = self._rows()
        eid = event_id(ev)
        if any(r["event_id"] == eid for r in rows):
            return None
        row = {**ev, "event_id": eid, "seq": (rows[-1]["seq"] + 1) if rows else 1, "recorded_at": at,
               "owner_alert": ev.get("stage") in OWNER_ALERT or bool(ev.get("exception"))}
        with self.events.open("a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def posted(self) -> dict:
        try:
            return json.loads(self.relay_state.read_text()).get("posted", {})
        except (OSError, ValueError):
            return {}

    def pending(self) -> list[dict]:
        done = self.posted()
        return [r for r in sorted(self._rows(), key=lambda r: r["seq"]) if r["event_id"] not in done]

    def relay(self, post: Callable[[str], Optional[str]]) -> dict:
        """Post pending events in order; stop at the first failure so order is kept and nothing is posted twice."""
        state = {"posted": self.posted()}
        sent, failed = 0, None
        for r in self.pending():
            ref = post(comment(r))
            if not ref:
                failed = r["event_id"]
                break
            state["posted"][r["event_id"]] = ref
            self.relay_state.write_text(json.dumps(state, indent=1, sort_keys=True))
            sent += 1
        return {"sent": sent, "failed_at": failed, "pending": len(self.pending())}


def comment(r: dict) -> str:
    return "\n".join([
        f"DEAL SNIFFER: {r['task']} — {r['stage']}",
        f"Result/current work: {r.get('evidence') or r.get('summary') or ''}"[:600],
        f"Evidence: {r.get('commit') or r.get('receipt') or r.get('evidence') or 'see receipt'}"[:300],
        f"ETA: {r.get('eta') or 'UNKNOWN'}",
        f"next_check_at: {r.get('next_check_at') or 'MISSING'}",
        f"Blocker: {r.get('blocker') or 'NONE'}",
        f"Host observation: {r.get('host_observed_at') or 'UNKNOWN'}",
        f"Next bounded item/action: {r.get('next_item') or 'see queue'}",
        f"(event {r['event_id']} #{r['seq']}; transport only — truth is the repo receipts)"])


def gh_ready() -> bool:
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def gh_post(body: str) -> Optional[str]:
    try:
        r = subprocess.run(["gh", "pr", "comment", str(PR_NUMBER), "--repo", PR_REPO, "--body", body], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (r.stdout.strip() or "posted") if r.returncode == 0 else None


def worker_alive(task: str, ps_lines: list[str]) -> bool:
    """A real `python ... tools/worker.py <task> ...` process (shell wrappers and process checks that merely mention it do not count)."""
    pat = re.compile(rf"^\s*\d+\s+\S*python\S*\s+(?:-\S+\s+)*\S*tools/worker\.py\s+{re.escape(task)}(\s|$)")
    return any(pat.search(x) for x in ps_lines)


class Checkpoints:
    def __init__(self, wd: Path):
        self.path = Path(wd) / "checkpoints.json"

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def save(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d, indent=1, sort_keys=True))

    def record(self, rec: dict, outbox: Outbox, *, at: str, now: Optional[datetime] = None) -> dict:
        """ACK/WORKING need the full ETA schema; other stages need project, task, stage and evidence. DONE is published immediately
        (flagged early when it lands before next_check_at) and closes the checkpoint."""
        if rec.get("stage") in ("ACK", "WORKING"):
            errs = validate(rec)
        else:
            errs = [f"missing {k}" for k in ("project", "task", "stage", "evidence") if not str(rec.get(k) or "").strip()]
            errs += [e for e in validate({**{k: "x" for k in REQUIRED}, "next_check_at": "2026-01-01 00:00 CST", **{k: rec[k] for k in ("project", "stage") if k in rec}}) if not e.startswith("missing")]
        if errs:
            raise ValueError("; ".join(errs))
        d = self.load()
        if rec["stage"] in ("ACK", "WORKING"):
            d[rec["task"]] = rec
        elif rec["stage"] in ("DONE", "NEED", "BLOCKED"):
            open_cp = d.get(rec["task"]) or {}
            if rec["stage"] == "DONE" and open_cp.get("next_check_at") and not open_cp.get("closed"):
                rec = {**rec, "early": not due(open_cp, now or datetime.now(CHICAGO))}
            d.setdefault(rec["task"], {}).update({"closed": rec["stage"], "closed_ref": rec.get("commit") or rec.get("receipt") or rec.get("evidence")})
        self.save(d)
        return outbox.add(rec, at=at) or {}


def tick(wd: Path, now: datetime, ps_lines: list[str], observed_at: str, post: Optional[Callable[[str], Optional[str]]] = None) -> dict:
    """One watchdog cycle: decide due checkpoints (exactly one outcome each), then relay pending events when a transport exists."""
    cps, ob = Checkpoints(wd), Outbox(wd)
    d = cps.load()
    outcomes = []
    for task, rec in sorted(d.items()):
        if rec.get("closed") or not rec.get("next_check_at"):
            continue
        out = decide(rec, now=now, done_ref=rec.get("done_ref"), worker_alive=worker_alive(task, ps_lines) if ps_lines is not None else None, observed_at=observed_at)
        if not out:
            continue
        ob.add(out, at=observed_at)
        outcomes.append(out)
        if out["stage"] == "WORKING":
            rec.update(next_check_at=out["next_check_at"], eta=out["eta"])
        else:
            rec.update(closed=out["stage"], closed_ref=out["evidence"])
    cps.save(d)
    relay = ob.relay(post) if post else {"sent": 0, "pending": len(ob.pending()), "need": "relay transport unavailable: `gh` is not authenticated on this host (owner: run `gh auth login`)"}
    return {"outcomes": outcomes, "relay": relay}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Record an ETA checkpoint (validated) into the watchdog outbox.")
    ap.add_argument("stage", choices=STAGES)
    for k in ("task", "responsible", "evidence", "eta", "next-check", "acceptance", "blocker", "commit", "receipt", "next-item"):
        ap.add_argument(f"--{k}")
    ap.add_argument("--wd", default=str(Path(__file__).resolve().parents[1] / "var" / "watchdog"))
    a = ap.parse_args(argv)
    rec = {"project": PROJECT, "stage": a.stage, "task": a.task, "responsible": a.responsible or "Agent 01", "evidence": a.evidence, "eta": a.eta,
           "next_check_at": a.next_check, "acceptance": a.acceptance, "blocker": a.blocker or "NONE", "commit": a.commit, "receipt": a.receipt,
           "next_item": a.next_item}
    rec = {k: v for k, v in rec.items() if v is not None}
    try:
        row = Checkpoints(Path(a.wd)).record(rec, Outbox(Path(a.wd)), at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except ValueError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"recorded": bool(row), "event_id": row.get("event_id"), "seq": row.get("seq")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
