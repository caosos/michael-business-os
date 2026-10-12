"""F-156: the compact 'Sources' panel on /market. Display only: every row comes from `market_sources.REGISTRY` plus a light read of the caches;
there is no second list. A fixture or candidate is never LIVE CONNECTED. All text escaped."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from . import market_sources as msrc

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def rows(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for info in msrc.REGISTRY:
        pr = msrc.probe(info, now)
        out.append({"info": info, "probe": pr, "state": msrc.source_state(info, pr)})
    return out


def _fresh(pr: dict) -> str:
    if pr["status"] == "connected":
        return f"last success {e(str(pr['as_of'])[:16].replace('T', ' '))} UTC ({pr['age_h']:g} h ago){' · STALE' if pr['stale'] else ''}"
    if pr["status"] == "fixture":
        return "FIXTURE / not live: test e-mails only, no real read"
    if pr["status"] == "manual":
        return f"{pr['n']} owner-entered find(s)"
    return "never read on this machine"


def render(now: datetime | None = None) -> str:
    body = ""
    for r in rows(now):
        i, pr, st = r["info"], r["probe"], r["state"]
        cls = "" if st == "LIVE CONNECTED" else " class='mut'"
        body += (f"<tr data-src='{e(i.key)}' data-state='{e(st)}'{cls}><td><b>{e(i.name)}</b><br><span class='small'>{e(i.cls)}</span></td><td>{e(i.geography)}</td>"
                 f"<td>{e(i.path)}<br><span class='small'>{e(i.granularity)}</span></td><td class='small'>{e(i.bidding)}</td><td class='small'>{_fresh(pr)}</td>"
                 f"<td class='small'>{e(i.constraint)}</td><td><span class='badge'>{e(st)}</span></td><td class='small'>{e(i.next_step)}</td></tr>")
    head = "".join(f"<th>{h}</th>" for h in ("Source", "Geography", "Retrieval / granularity", "Account / bid", "Freshness", "Constraints", "State", "Next step"))
    return (f"<details class='card' id='sources-panel'><summary><b>Sources</b> <span class='small mut'>(what this page can and cannot see; fixtures never count as live)</span></summary>"
            f"<table class='small' style='width:100%'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></details>")
