"""F-145: per-source coverage/status line, the FIXTURE / not live labelling and the NOT CONNECTED states for /market. Pure markup; all text escaped.
Only GSA (cached file) is ever called connected. A parser-backed .eml fixture is FIXTURE / not live; every other source is NOT CONNECTED."""

from __future__ import annotations

import html

from . import market_search as ms
from . import market_sources as msrc

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
FIXTURE_BANNER = ("FIXTURE / not live: scrubbed test e-mails read from a local directory on an isolated staging server. These are not Michael's real deals, "
                  "no mailbox is read, and nothing here counts as a connected source.")
ALWAYS_OFF = ("Craigslist", "eBay", "Facebook Marketplace")


def source_options() -> list[tuple[str, str]]:
    fx = msrc.fixture_dir() is not None
    alerts = [(k, f"{n} (FIXTURE, not live)" if fx else f"{n} (not connected)") for k, (_, n) in msrc.ALERT_SOURCES.items()]
    return [("gsa", "GSA Auctions")] + alerts + [("all", "All sources (merged)")] + [(n.lower(), n + " (not connected)") for n in ALWAYS_OFF]


def _row(c: dict) -> str:
    n = e(c["name"])
    if c["status"] == "connected":
        age = f" · last fetched {e(str(c['as_of'])[:16].replace('T', ' '))} UTC ({c['age_h']:g} h ago){' · <b class=bad>STALE</b>' if c['stale'] else ''} · {c['in_scope']} lots"
        return f"<li data-src='{n}' data-status='connected'><b>{n}: connected (cached file)</b>{age}</li>"
    if c["status"] == "fixture":
        return (f"<li data-src='{n}' data-status='fixture'><b class='bad'>{n}: FIXTURE / not live</b> · {c['in_scope']} test listing(s) · newest test e-mail dated "
                f"{e(str(c['as_of'])[:16].replace('T', ' '))} UTC{' · STALE' if c['stale'] else ''}</li>")
    return f"<li data-src='{n}' data-status='{e(c['status'])}'><b>{n}: NOT CONNECTED</b> · no mailbox read, nothing shown</li>"


def coverage(d: dict) -> str:
    """Status block for a non-GSA source page (govdeals | publicsurplus | all)."""
    rows = "".join(_row(c) for c in d.get("coverage") or [{k: d.get(k) for k in ("name", "status", "as_of", "age_h", "stale", "in_scope")}])
    off = "".join(f"<li data-src='{e(n)}' data-status='not_connected'><b>{e(n)}: NOT CONNECTED</b></li>" for n in ALWAYS_OFF)
    banner = f"<div class='flash err' id='fixture-banner' role='note'><b>{e(FIXTURE_BANNER)}</b></div>" if d.get("fixture") else ""
    return f"{banner}<ul class='small' id='source-status' style='margin:6px 0;padding-left:18px'>{rows}{off}</ul>"


def gate(q: dict, d: dict) -> str | None:
    """The body for a source that has no read to show, else None. A single alert source without the staging fixtures is NOT CONNECTED."""
    s = q["source"]
    if s == "gsa" or s == "all":
        return None
    if s in msrc.ALERT_SOURCES and d["status"] == "fixture":
        return None
    return f"<div class='card'><b>{e(msrc.ALERT_SOURCES[s][1] if s in msrc.ALERT_SOURCES else s)}: not connected.</b> No results are shown for a source that is not wired; nothing is mocked.</div>"


def card_note(c: dict) -> str:
    return (f"<div class='small'><span class='badge'>FIXTURE / not live</span> {e(c['source'])} · fetched {e(c['fetched_at'])}</div>") if c.get("fixture") else ""


def scope_line(d: dict) -> str:
    if d.get("fixture"):
        return "Parser-backed test e-mails (FIXTURE, not live), merged with the cached GSA list when all sources are chosen. Price = alert text, not a sold price or final cost; all-in cost UNKNOWN."
    return "Cached copy of the GSA list, not a fresh fetch (GSA surplus only). Price = current bid, not a sold price or final cost; all-in cost UNKNOWN."
