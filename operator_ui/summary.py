"""F-12: daily summary, generated LOCALLY and NEVER SENT.

Sections: digest top-N (lane C's ranking, unchanged) · HOLD backlog with overdue items · yesterday's
outcomes · source health. Output: a markdown file, a standalone HTML file and the `/summary` UI page.

* Deterministic: every time-dependent choice uses the `as_of` argument (no wall clock). Lists are
  sorted explicitly, and a `summary_hash` (MBOS-CJSON-1) of the assembled data is printed in the header.
  Same store state + same `as_of` produce byte-identical files.
* Never sent: there are no network imports (test-enforced), no email/SMS code, and files are only
  written to a local directory, atomically.
* Untrusted text (listing titles, notes, remote error messages) is escaped for markdown and for HTML.
"""

from __future__ import annotations

import html
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from mbos.clock import iso

from . import digest as digest_view
from . import mbos_canonical
from .card_view import ec
from .sources import load_health

LOCAL_TZ = ZoneInfo("America/Chicago")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _yesterday_bounds(as_of: datetime) -> tuple[datetime, datetime]:
    local = as_of.astimezone(LOCAL_TZ)
    start_today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_today - timedelta(days=1), start_today


def build_summary(store: Any, as_of: datetime, *, top_n: int = 10, health_file: Optional[str] = None) -> dict:
    """Assemble the summary data (read-only). `store` is a SpineBackend (or any object with the same readers)."""
    as_of_s = iso(as_of)
    dv = digest_view.build(store, as_of_s, limit=top_n)
    d = dv["digest"]
    digest = {"error": dv["error"],
              "rows": [{k: r[k] for k in ("rank", "bucket", "lane", "category", "title", "action", "reason", "window",
                                          "value_per_hour", "rank_score", "ev_decision", "ev_profit_per_hour", "item_id")} | {"provenance_id": r["refs"]["provenance_id"]}
                       for r in (d["rows"] if d else [])],
              "counts": d["counts"] if d else {}, "digest_hash": d["digest_hash"] if d else None,
              "not_ranked": len(dv["precheck_excluded"]) + (len(d["excluded"]) if d else 0)}

    holds = []
    for h in store.held():
        until = h["hold"].get("hold_until")
        holds.append({"item_id": h["item"]["item_id"], "title": h["item"]["normalized"]["title"], "lane": h["item"]["type"],
                      "action_request_id": h["action_request"]["action_request_id"],
                      "capability": h["action_request"]["capability"], "held_at": h["held_at"], "hold_until": until,
                      "overdue": bool(until) and _ts(until) <= as_of, "reason": h.get("reason")})
    holds.sort(key=lambda h: (not h["overdue"], h["hold_until"] or "9999", h["action_request_id"]))

    y0, y1 = _yesterday_bounds(as_of)
    outs = []
    for o in store.outcomes(limit=1000):
        obs = _ts(o["observed_at"])
        if y0 <= obs < y1:
            item = store.item(o["item_id"]) or {"normalized": {"title": o["item_id"]}, "type": "?"}
            outs.append({"outcome_id": o["outcome_id"], "item_id": o["item_id"], "title": item["normalized"]["title"],
                         "lane": item["type"], "kind": o["kind"], "observed_at": o["observed_at"],
                         "net_profit": (o.get("realized") or {}).get("net_profit"), "notes": o.get("notes")})
    outs.sort(key=lambda o: (o["observed_at"], o["outcome_id"]))
    net = sum(o["net_profit"] for o in outs if isinstance(o["net_profit"], (int, float)))

    h = load_health(health_file)
    sources = {"error": h["error"], "path": h["path"],
               "updated_at": iso(h["updated_at"]) if h["updated_at"] else None,
               "stale": bool(h["updated_at"]) and (as_of - h["updated_at"]) > timedelta(hours=24),
               "rows": [{k: r[k] for k in ("source", "status", "consecutive_blocks", "last_success_at", "freeze_reason")}
                        for r in h["rows"]]}

    body = {"as_of": as_of_s, "local_date": as_of.astimezone(LOCAL_TZ).date().isoformat(), "top_n": top_n,
            "yesterday": {"from": iso(y0), "to": iso(y1)}, "digest": digest, "holds": holds,
            "outcomes": {"rows": outs, "net_profit": net}, "sources": sources}
    return {**body, "summary_hash": mbos_canonical.sha256_of(_jsonable(body))}


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_jsonable(v) for v in o]
    return o


# ---------------------------------------------------------------- rendering
_MD_SPECIAL = re.compile(r"([\\`*_\[\]{}()#+!|>~-])")


def md(text: Any) -> str:
    """Markdown-safe inline text: no newlines, markdown syntax escaped, HTML neutralised."""
    from mbos.card import clean_text

    s = clean_text("" if text is None else text, 400)  # control / ANSI / bidi stripped, length capped
    s = re.sub(r"\s+", " ", s).strip()
    s = html.escape(s, quote=False)
    return _MD_SPECIAL.sub(r"\\\1", s)


def _fig(r: dict) -> dict:
    """F-95: one figure per concept: the rank score is a plain number (never $), expected profit is dollars."""
    from .digest import dollars, figures

    g = figures(r)
    return {"priority": dollars(g["priority"], ""), "ev": dollars(g["ev"])}


def _money(v: Any) -> str:
    return "—" if not isinstance(v, (int, float)) else f"${v:,.0f}"


def render_markdown(s: dict) -> str:
    L = [f"# MBOS daily summary — {s['local_date']}", "",
         f"_Generated locally, never sent._ As of `{s['as_of']}` · summary hash `{s['summary_hash']}`", ""]
    d = s["digest"]
    L += [f"## Do first (digest top {s['top_n']})", ""]
    if d["error"]:
        L += [f"**Digest unavailable:** {md(d['error'])}", ""]
    elif not d["rows"]:
        L += ["Nothing open to rank.", ""]
    else:
        L += ["| # | Bucket | Lane | Opportunity | Next step | Window | Priority score | Expected profit |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {r['rank']} | {md(r['bucket'])} | {md(r['lane'])} | {md(r['title'])} | {md(r['action'])} | "
              f"{md(r['window'])} | {_fig(r)['priority']} | {_fig(r)['ev']} |" for r in d["rows"]]
        L += ["", f"Lane C digest hash `{d['digest_hash']}`; {d['not_ranked']} item(s) not ranked (see the UI).", ""]
    over = [h for h in s["holds"] if h["overdue"]]
    L += [f"## HOLD backlog ({len(s['holds'])}, {len(over)} overdue)", ""]
    if s["holds"]:
        L += ["| Opportunity | Action | Wakes at | Status | Reason |", "|---|---|---|---|---|"]
        L += [f"| {md(h['title'])} | {md(h['capability'])} | {md(h['hold_until'])} | "
              f"{'**OVERDUE**' if h['overdue'] else 'waiting'} | {md(h['reason'])} |" for h in s["holds"]]
    else:
        L += ["Nothing is parked."]
    o = s["outcomes"]
    L += ["", f"## Yesterday's outcomes ({len(o['rows'])}, net {_money(o['net_profit'])})", ""]
    if o["rows"]:
        L += ["| Opportunity | Lane | Outcome | Net | Notes |", "|---|---|---|---|---|"]
        L += [f"| {md(r['title'])} | {md(r['lane'])} | {md(r['kind'])} | {_money(r['net_profit'])} | {md(r['notes'])} |"
              for r in o["rows"]]
    else:
        L += ["No outcomes recorded yesterday."]
    src = s["sources"]
    L += ["", "## Source health", ""]
    if src["error"]:
        L += [f"**Unavailable:** {md(src['error'])}"]
    else:
        frozen = [r for r in src["rows"] if r["status"] != "HEALTHY"]
        L += [f"{len(src['rows'])} sources, {len(frozen)} not healthy" + (" · **health data STALE (>24 h)**" if src["stale"] else "") + ".", ""]
        L += [f"- **{md(r['source'])}**: {md(r['status'])}" + (f" — {md(r['freeze_reason'])}" if r["freeze_reason"] else "")
              for r in frozen]
    L += ["", "---", "DRY-RUN system. This file was written locally and was not emailed, texted or posted.", ""]
    return "\n".join(L)


def render_html_body(s: dict) -> str:
    e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
    d = s["digest"]
    parts = [f"<h1>MBOS daily summary — {e(s['local_date'])}</h1>",
             f"<p class='small mut'>Generated locally, never sent. As of <code>{e(s['as_of'])}</code> · summary hash "
             f"<code>{e(s['summary_hash'])}</code></p>", f"<h2>Do first (digest top {e(s['top_n'])})</h2>"]
    if d["error"]:
        parts.append(f"<p class='bad'>Digest unavailable: {e(d['error'])}</p>")
    else:
        rows = "".join(f"<tr><td>{e(r['rank'])}</td><td>{e(r['bucket'])}</td><td>{e(r['lane'])}</td><td>{ec(r['title'])}</td>"
                       f"<td>{e(r['action'])}</td><td>{e(r['window'])}</td><td>{e(_fig(r)['priority'])}</td><td>{e(_fig(r)['ev'])}</td></tr>"
                       for r in d["rows"])
        parts.append("<table><tr><th>#</th><th>Bucket</th><th>Lane</th><th>Opportunity</th><th>Next step</th><th>Window</th>"
                     f"<th title='Lane C rank score: orders the list; not dollars'>Priority score</th><th>Expected profit</th></tr>{rows or '<tr><td colspan=8>Nothing open to rank.</td></tr>'}</table>")
    over = sum(h["overdue"] for h in s["holds"])
    rows = "".join(f"<tr><td>{ec(h['title'])}</td><td>{e(h['capability'])}</td><td>{e(h['hold_until'])}</td>"
                   f"<td class='{'bad' if h['overdue'] else ''}'>{'OVERDUE' if h['overdue'] else 'waiting'}</td><td>{e(h['reason'])}</td></tr>"
                   for h in s["holds"])
    parts.append(f"<h2>HOLD backlog ({len(s['holds'])}, {over} overdue)</h2>" + (
        f"<table><tr><th>Opportunity</th><th>Action</th><th>Wakes at</th><th>Status</th><th>Reason</th></tr>{rows}</table>"
        if rows else "<p>Nothing is parked.</p>"))
    o = s["outcomes"]
    rows = "".join(f"<tr><td>{ec(r['title'])}</td><td>{e(r['lane'])}</td><td>{e(r['kind'])}</td><td>{e(_money(r['net_profit']))}</td>"
                   f"<td>{e(r['notes'])}</td></tr>" for r in o["rows"])
    parts.append(f"<h2>Yesterday's outcomes ({len(o['rows'])}, net {e(_money(o['net_profit']))})</h2>" + (
        f"<table><tr><th>Opportunity</th><th>Lane</th><th>Outcome</th><th>Net</th><th>Notes</th></tr>{rows}</table>"
        if rows else "<p>No outcomes recorded yesterday.</p>"))
    src = s["sources"]
    if src["error"]:
        parts.append(f"<h2>Source health</h2><p class='bad'>Unavailable: {e(src['error'])}</p>")
    else:
        bad = [r for r in src["rows"] if r["status"] != "HEALTHY"]
        items = "".join(f"<li><b>{e(r['source'])}</b>: {e(r['status'])}{' — ' + e(r['freeze_reason']) if r['freeze_reason'] else ''}</li>"
                        for r in bad)
        parts.append(f"<h2>Source health</h2><p>{len(src['rows'])} sources, {len(bad)} not healthy"
                     f"{' · <b class=bad>STALE (&gt;24 h)</b>' if src['stale'] else ''}.</p>" + (f"<ul>{items}</ul>" if items else ""))
    parts.append("<p class='small mut'>DRY-RUN system. Written locally; not emailed, texted or posted.</p>")
    return "\n".join(parts)


def render_html_document(s: dict) -> str:
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>MBOS daily summary {html.escape(s['local_date'])}</title>"
            "<style>body{font:15px/1.45 system-ui,sans-serif;max-width:960px;margin:0 auto;padding:16px}"
            "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:4px 6px;text-align:left}"
            ".bad{color:#b3261e}.mut{color:#666}.small{font-size:13px}</style></head><body>"
            + render_html_body(s) + "</body></html>\n")


def write_files(s: dict, out_dir: str | Path) -> dict[str, str]:
    """Write daily-summary-<local_date>.md/.html atomically into a LOCAL directory. Returns the paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for ext, text in (("md", render_markdown(s)), ("html", render_html_document(s))):
        target = out / f"daily-summary-{s['local_date']}.{ext}"
        fd, tmp = tempfile.mkstemp(dir=out, prefix=".tmp-", suffix=f".{ext}")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, target)
        paths[ext] = str(target)
    return paths
