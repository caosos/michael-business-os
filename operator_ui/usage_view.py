"""F-21: the usage / agent dashboard (ADR-0014), a READ-ONLY render of `mbos.telemetry.summarize`.

* Telemetry comes from `$MBOS_TELEMETRY_DIR/worker_runs.jsonl` (default `<repo>/var/telemetry`). The file is only read: the
  directory is never created (unlike `mbos.telemetry.default_path`).
* Task states come from a READY_QUEUE.md file (`MBOS_READY_QUEUE_FILE`); with none set they are UNKNOWN.
* UNKNOWN stays UNKNOWN: an empty file, a missing figure or an unreadable file never becomes 0. If the hash chain fails
  verification the figures are NOT shown (only the errors), because an edited row cannot be trusted.
* Cost is Claude Code's own estimate, not a bill. Fable weekly % and the contributor splits have no programmatic source:
  they show a manual snapshot if one exists, else UNKNOWN.
* Human channel only (R14): loopback, Host-checked, no forms, no writes, no approval.
"""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any, Optional

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
UNK = "<b class='unk'>UNKNOWN</b>"
MODELS = ("sonnet", "opus", "fable", "haiku")
COST_LABEL = "Claude Code estimate, not a bill"


def telemetry_file(directory: Optional[str] = None) -> Path:
    base = directory or os.environ.get("MBOS_TELEMETRY_DIR")
    return (Path(base) if base else Path(__file__).resolve().parent.parent / "var" / "telemetry") / "worker_runs.jsonl"


def load(directory: Optional[str] = None) -> dict:
    """{'path', 'rows', 'summary', 'errors'}. Never raises. `summary` is None if the file could not be read or parsed."""
    from mbos import telemetry

    p = telemetry_file(directory)
    try:
        rows = telemetry.read(p)
        if not all(isinstance(r, dict) for r in rows):
            raise ValueError("a row is not a JSON object")
        s = telemetry.summarize(rows)
    except (OSError, ValueError, TypeError, KeyError) as ex:
        return {"path": str(p), "rows": [], "summary": None, "errors": [f"telemetry unreadable: {type(ex).__name__}: {ex}"]}
    return {"path": str(p), "rows": rows, "summary": s, "errors": list(s["chain_errors"])}


def queue_states(path: Optional[str] = None) -> Optional[dict[str, list[tuple[str, str]]]]:
    """{'active'|'queued'|'blocked': [(task id, title)]} from READY_QUEUE.md table rows; None (UNKNOWN) if no readable file."""
    p = path or os.environ.get("MBOS_READY_QUEUE_FILE")
    if not p:
        return None
    try:
        text = Path(p).read_text(encoding="utf-8")
    except OSError:
        return None
    out: dict[str, list[tuple[str, str]]] = {"active": [], "queued": [], "blocked": []}
    kind = {"CLAIMED": "active", "READY": "queued", "BLOCKED": "blocked"}
    for ln in text.splitlines():
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if ln.lstrip().startswith("|") and len(c) >= 6 and c[0][:1].isalpha() and "-" in c[0]:
            word = c[4].replace("*", "").strip().split(" ")[0].split(":")[0].upper()
            if word in kind:
                out[kind[word]].append((c[0], c[2][:120]))
    return out


def _n(v: Any, fmt: str = "{}") -> str:
    return UNK if v is None else e(fmt.format(v))


def render_quota(rows: list[dict]) -> str:
    snaps = [r for r in rows if r.get("kind") == "quota_snapshot"]
    if not snaps:
        return ("<div class='card'><h2>Quota</h2><p class='unk'>UNKNOWN: no quota snapshot recorded. Source: none (a worker run records the 5-hour and "
                "weekly % from Claude Code's rate-limit event; Fable % and contributor splits are manual entries only).</p></div>")
    last = snaps[-1]
    fable = next((r for r in reversed(snaps) if r.get("week_fable_pct") is not None), None)

    def line(label: str, v: Any, src: Any, at: Any) -> str:
        return f"<tr><td>{label}</td><td>{_n(v, '{}%')}</td><td>{e(src)}</td><td>{e(at)}</td></tr>"

    return ("<div class='card'><h2>Quota</h2><table><tr><th>Window</th><th>Used</th><th>Source</th><th>Recorded at</th></tr>"
            + line("5-hour", last.get("session_pct"), last.get("source", "UNKNOWN"), last.get("at"))
            + line("Weekly (all models)", last.get("week_all_pct"), last.get("source", "UNKNOWN"), last.get("at"))
            + line("Weekly Fable", fable.get("week_fable_pct") if fable else None,
                   fable.get("source", "UNKNOWN") if fable else "UNKNOWN (manual only)", fable.get("at") if fable else None)
            + f"<tr><td>Contributor splits</td><td>{UNK}</td><td>UNKNOWN (manual only; not in telemetry)</td><td></td></tr></table>"
            + f"<p class='small mut'>A snapshot is only as current as its time. Resets: {e(last.get('session_resets_at') or last.get('resets'))} / "
              f"{e(last.get('week_resets_at'))}.</p></div>")


def render_queue(q: Optional[dict]) -> str:
    if q is None:
        return ("<div class='card'><h2>Tasks</h2><p class='unk'>UNKNOWN: no READY_QUEUE file (set MBOS_READY_QUEUE_FILE; read it with "
                "<code>git show origin/research/agent-01-coordinator:docs/status/READY_QUEUE.md</code>).</p></div>")
    cells = "".join(f"<td><b>{e(len(q[k]))}</b> {label}<ul class='small'>" + "".join(f"<li><code>{e(i)}</code> {e(t)}</li>" for i, t in q[k][:15])
                    + "</ul></td>" for k, label in (("active", "active (CLAIMED)"), ("queued", "queued (READY)"), ("blocked", "blocked")))
    return f"<div class='card'><h2>Tasks</h2><table><tr>{cells}</tr></table></div>"


def render_page(loaded: dict, queue: Optional[dict] = None) -> str:
    head = ("<div class='card'><h2>Usage and agents</h2><p class='small mut'>Read-only. From the worker telemetry chain "
            f"(<code>{e(loaded['path'])}</code>). Nothing here approves, spends, contacts or launches anything.</p></div>")
    if loaded["errors"]:
        return (head + "<div class='flash err'><b>TELEMETRY FAILED VERIFICATION OR COULD NOT BE READ, so no figures are shown.</b><ul>"
                + "".join(f"<li>{e(x)}</li>" for x in loaded["errors"][:12]) + "</ul></div>" + render_queue(queue))
    s, rows = loaded["summary"], loaded["rows"]
    runs = [r for r in rows if r.get("kind") == "worker_run"]
    if not runs:
        return (head + "<div class='card'><p class='unk'><b>No worker runs recorded: every figure below is UNKNOWN.</b></p></div>"
                + render_queue(queue) + render_quota(rows))
    mix = {m: 0 for m in MODELS}
    other: dict[str, int] = {}
    for k, v in s["model_mix"].items():
        if k.lower() in mix:
            mix[k.lower()] = v
        else:
            other[k] = v
    mixh = ", ".join(f"{e(k)} {e(v)}" for k, v in {**mix, **other}.items())
    turns = [r["num_turns"] for r in runs if r.get("num_turns") is not None]
    cost = s["cost_estimate_usd_total"] if any(r.get("cost_estimate_usd") is not None for r in runs) else None
    done = s.get("tasks_completed")                      # older mbos pins do not summarize it: count the rows' flag, else UNKNOWN
    if done is None and any("task_completed" in r for r in runs):
        done = sum(1 for r in runs if r.get("task_completed"))
    dur = s["avg_duration_ms"]
    days = "".join(f"<li>{e(d) if d else 'UNKNOWN date'}: {e(n)}</li>" for d, n in sorted(s["throughput_per_day"].items()))
    stats = (f"<div class='card'><h2>Worker runs</h2><table>"
             f"<tr><td>Runs</td><td>{e(s['runs'])} ({e(s['succeeded'])} succeeded, {e(s['failed'])} failed)</td></tr>"
             f"<tr><td>Tasks completed (DONE report + new commit)</td><td>{_n(done)}</td></tr>"
             f"<tr><td>Model mix (as requested)</td><td>{mixh}</td></tr>"
             f"<tr><td>Average duration</td><td>{UNK if dur is None else e(f'{dur / 1000:.0f} s')}</td></tr>"
             f"<tr><td>Turns (total / average)</td><td>{UNK if not turns else e(f'{sum(turns)} / {sum(turns) / len(turns):.1f}')}</td></tr>"
             f"<tr><td>Escalations / retries</td><td>{e(s['escalations'])} / {e(s['retries'])}</td></tr>"
             f"<tr><td>Cost ({e(COST_LABEL)})</td><td>{UNK if cost is None else e(f'${cost:.2f}')}"
             f" <span class='small mut'>{e(COST_LABEL)}; not a separate bill under Max.</span></td></tr></table>"
             f"<p class='small'>Throughput per day (by run end):</p><ul class='small'>{days}</ul></div>")
    last = "".join(f"<tr><td>{e(r.get('task_id'))}</td><td>{e(r.get('lane'))}</td><td>{e(r.get('model_requested'))}</td>"
                   f"<td>{'done' if r.get('task_completed') else ('ok, not done' if r.get('success') else 'failed')}</td>"
                   f"<td>{_n(r.get('num_turns'))}</td><td>{e(r.get('ended_at'))}</td></tr>" for r in runs[-10:][::-1])
    recent = f"<div class='card'><h2>Recent runs</h2><table><tr><th>Task</th><th>Lane</th><th>Model</th><th>Result</th><th>Turns</th><th>Ended</th></tr>{last}</table></div>"
    return head + render_queue(queue) + stats + recent + render_quota(rows)
