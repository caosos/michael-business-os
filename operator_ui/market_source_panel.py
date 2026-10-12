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
    if pr["status"] == "waiting":
        return f"mailbox read {e(str(pr['as_of'])[:16].replace('T', ' '))} UTC ({pr['age_h']:g} h ago); no alert from this source yet"
    if pr["status"] == "manual":
        return f"{pr['n']} owner-entered find(s)"
    return "never read on this machine"


def render(now: datetime | None = None, status: str = "") -> str:
    """`status`: the per-source status block (F-163: shown here, collapsed, on the browse page). The summary says how many sources are connected."""
    body = ""
    rs = rows(now)
    n_on = sum(1 for r in rs if r["state"] == "LIVE CONNECTED")
    for r in rs:
        i, pr, st = r["info"], r["probe"], r["state"]
        cls = "" if st == "LIVE CONNECTED" else " class='mut'"
        body += (f"<tr data-src='{e(i.key)}' data-state='{e(st)}'{cls}><td><b>{e(i.name)}</b><br><span class='small'>{e(i.cls)}</span></td><td>{e(i.geography)}</td>"
                 f"<td>{e(i.path)}<br><span class='small'>{e(i.granularity)}</span></td><td class='small'>{e(i.bidding)}</td><td class='small'>{_fresh(pr)}</td>"
                 f"<td class='small'>{e(i.constraint)}</td><td><span class='badge'>{e(st)}</span></td><td class='small'>{e(i.next_step)}</td></tr>")
    head = "".join(f"<th>{h}</th>" for h in ("Source", "Geography", "Retrieval / granularity", "Account / bid", "Freshness", "Constraints", "State", "Next step"))
    one = f"<span class='small' id='sources-summary'>{n_on} connected, {len(rs) - n_on} not connected</span> "
    return (f"<details class='card' id='sources-panel'><summary><b>Sources</b> {one}<span class='small mut'>(what this page can and cannot see; fixtures never count as live)</span></summary>"
            f"{status}<table class='small' style='width:100%'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></details>")
