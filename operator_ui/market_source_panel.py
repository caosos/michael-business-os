"""F-156: the compact 'Sources' panel on /market. Display only: every row comes from `market_sources.REGISTRY` plus a light read of the caches;
there is no second list. A fixture or candidate is never LIVE CONNECTED. All text escaped."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from . import market_sources as msrc

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def display_kind(row: dict) -> str:
    """Return the owner-facing availability kind without overstating inventory.

    The registry's ``LIVE CONNECTED`` state is an internal provenance gate: it
    can mean either a provider produced a successful cache or that a local
    cache file is readable.  Those are materially different things in the
    Marketplace source picker, especially when the current filters match zero
    rows, so the picker never collapses both into the word ``connected``.
    """
    info, probe, state = row["info"], row["probe"], row["state"]
    if info.historical_only:
        return "historical" if probe.get("status") == "connected" else "not_connected"
    if probe.get("status") == "fixture":
        return "fixture"
    if state == "BLOCKED":
        return "blocked"
    if state == "IMPORTED":
        return "imported"
    if state == "MANUAL":
        return "manual"
    if state == msrc.WAITING:
        return "waiting"
    if state != "LIVE CONNECTED":
        return "not_connected"
    if info.path == "provider API":
        return "provider"
    if info.path == "e-mail alerts":
        return "mailbox_cache"
    return "cache"


def display_status(row: dict, matching: int | None = None) -> str:
    """Plain-language source status, optionally qualified by this search."""
    kind = display_kind(row)
    label = {
        "provider": "live provider · cache ready",
        "historical": "historical cache · retrieval off",
        "cache": "cache ready",
        "mailbox_cache": "mailbox feed · cache ready",
        "waiting": "mailbox ready · waiting for alerts",
        "imported": "imported",
        "manual": "manual",
        "fixture": "FIXTURE · not live",
        "blocked": "blocked",
        "not_connected": "not connected",
    }[kind]
    if matching == 0 and kind in {"historical", "provider", "cache", "mailbox_cache", "waiting", "imported", "manual"}:
        label += " · no matches in this search"
    return label


def rows(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for info in msrc.REGISTRY:
        pr = msrc.probe(info, now)
        out.append({"info": info, "probe": pr, "state": msrc.source_state(info, pr)})
    return out


def _fresh(pr: dict) -> str:
    if pr["status"] == "connected" and pr.get("historical"):
        return (f"HISTORICAL CACHE retrieved {e(str(pr['as_of'])[:16].replace('T', ' '))} UTC ({pr['age_h']:g} h ago) · "
                "fresh retrieval is off: no paid provider")
    if pr["status"] == "connected":
        return f"last success {e(str(pr['as_of'])[:16].replace('T', ' '))} UTC ({pr['age_h']:g} h ago){' · STALE' if pr['stale'] else ''}"
    if pr["status"] == "fixture":
        return "FIXTURE / not live: test e-mails only, no real read"
    if pr["status"] == "waiting":
        return f"mailbox read {e(str(pr['as_of'])[:16].replace('T', ' '))} UTC ({pr['age_h']:g} h ago); no alert from this source yet"
    if pr["status"] == "manual":
        return f"{pr['n']} owner-entered find(s)"
    if pr["status"] == "imported":
        return (f"{pr['n']} active reviewed import(s) · last import {e(str(pr['as_of'])[:16].replace('T', ' '))} UTC"
                + (f" · {pr.get('expired', 0)} expired and hidden" if pr.get("expired") else ""))
    if pr.get("message"):
        return e(pr["message"])
    return "never read on this machine"


def render(now: datetime | None = None, status: str = "") -> str:
    """Render registry detail without treating every readable cache as a live connection."""
    body = ""
    rs = rows(now)
    for r in rs:
        i, pr, st = r["info"], r["probe"], r["state"]
        kind = display_kind(r)
        label = display_status(r)
        cls = "" if kind in {"historical", "provider", "cache", "mailbox_cache", "imported"} else " class='mut'"
        body += (f"<tr data-src='{e(i.key)}' data-state='{e(st)}'{cls}><td><b>{e(i.name)}</b><br><span class='small'>{e(i.cls)}</span></td><td>{e(i.geography)}</td>"
                 f"<td>{e(i.path)}<br><span class='small'>{e(i.granularity)}</span></td><td class='small'>{e(i.bidding)}</td><td class='small'>{_fresh(pr)}</td>"
                 f"<td class='small'>{e(i.constraint)}</td><td><span class='badge'>{e(label.upper())}</span></td><td class='small'>{e(i.next_step)}</td></tr>")
    head = "".join(f"<th>{h}</th>" for h in ("Source", "Geography", "Retrieval / granularity", "Account / bid", "Freshness", "Constraints", "State", "Next step"))
    counts = {k: sum(display_kind(r) == k for r in rs) for k in (
        "historical", "provider", "cache", "mailbox_cache", "waiting", "imported", "manual", "fixture", "blocked", "not_connected")}
    labels = (("historical", "historical cache"), ("provider", "live provider"), ("cache", "cache ready"), ("mailbox_cache", "mailbox cache ready"),
              ("waiting", "mailbox waiting"), ("imported", "imported"), ("manual", "manual"),
              ("fixture", "fixture"), ("blocked", "blocked"), ("not_connected", "not connected"))
    summary = " · ".join(f"{counts[k]} {label}" for k, label in labels if counts[k]) or "no sources configured"
    one = f"<span class='small' id='sources-summary'>{e(summary)}</span> "
    return (f"<details class='card' id='sources-panel'><summary><b>Sources</b> {one}<span class='small mut'>(what this page can and cannot see; fixtures never count as live)</span></summary>"
            f"{status}<table class='small' style='width:100%'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></details>")
