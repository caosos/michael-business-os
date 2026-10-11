"""F-139: the owner's own earlier decision on a similar listing, shown READ-ONLY on /market cards (a proposal for the owner's review).

Reads the owner-local store through `mbos.decision_cases.propose` only (no write, no network, no cache fetch). It never feeds filters, ranking,
hiding, saves or the learned prefs, and prints no bid/purchase/contact amount (a stored `amount_usd` is not rendered). Absent or empty store: nothing.
Disabled or failed-integrity store: one honest line. Any other error: nothing, never a crash."""
from __future__ import annotations

import html
import os
from contextlib import contextmanager
from pathlib import Path

e = html.escape
REPO_STORE = Path(__file__).resolve().parents[1] / "var" / "private" / "decision_cases"
SCOPE = "This is about that ONE earlier listing, not a preference for a category. It changes no filter, ranking, hiding or save."


@contextmanager
def _store():
    """mbos computes its default store path from its own install location; point it at this repo's private store unless the owner/test set one."""
    if os.environ.get("MBOS_DECISION_CASES_DIR"):
        yield
        return
    os.environ["MBOS_DECISION_CASES_DIR"] = str(REPO_STORE)
    try:
        yield
    finally:
        os.environ.pop("MBOS_DECISION_CASES_DIR", None)


def _li(items) -> str:
    return "".join(f"<li>{e(str(i))}</li>" for i in items)


def _ev(items) -> str:
    return _li(f"{x.get('kind', 'other')}: {x.get('text', '')}" for x in items)


def _est(items) -> str:
    out = []
    for x in items:
        if "label" in x:
            out.append(f"{x['label']}" + (f" ({x['note']})" if x.get("note") else ""))       # amount_usd is deliberately not shown
        else:
            out.append(f"{x.get('kind', 'other')}: {x.get('text', '')}")
    return _li(out)


def _part(title: str, items, fn=_li) -> str:
    return f"<p class='small' style='margin:2px 0'><b>{title}</b></p><ul class='small' style='margin:0 0 4px 18px'>{fn(items)}</ul>" if items else ""


def _match(m: dict) -> str:
    sc = m["source_case"]
    return (f"<div class='small' data-precedent='{e(str(sc.get('listing_id')))}'><p style='margin:2px 0'>You decided <b>{e(str(m['precedent_decision']).upper())}</b> on "
            f"“{e(str(sc.get('title') or sc.get('listing_id')))}” ({e(str(sc.get('source')))}, {e(str(sc.get('decided_at')))}). Reason: {e(str(m['reason_summary']))}</p>"
            + _part("Verified facts then", m["verified_facts"], _ev)
            + _part("YOUR ESTIMATES then (estimates, not facts)", m["owner_estimates_not_facts"], _est)
            + _part("Not verified then", m["unverified_evidence"], _ev)
            + _part("Uncertainty then", m["uncertainty"]) + _part("Missing evidence then", m["missing_evidence_then"])
            + _part("Evidence that decision relied on and this listing lacks (nothing checked here yet)", m["evidence_kinds_the_case_relied_on_that_the_candidate_lacks"])
            + f"<p class='mut small' style='margin:2px 0'>Shared words: {e(', '.join(m['similarity']['shared_terms']))}. {e(m['precedent_scope'].capitalize())}.</p></div>")


def block(p: dict) -> str:
    ms = p.get("matches") or []
    if not ms:
        return ""
    return ("<details class='small mk-prec' data-testid='precedent'><summary>Your earlier decision on a similar listing (proposal, for your review)</summary>"
            + "".join(_match(m) for m in ms[:3]) + (f"<p class='mut small'>{len(ms) - 3} more similar earlier decision(s) not shown.</p>" if len(ms) > 3 else "")
            + f"<p class='mut small'>{e(SCOPE)} Not a bid, purchase or contact suggestion; hard filters and evidence checks still apply.</p></details>")


def for_cards(cards: list[dict]) -> tuple[dict, str]:
    """({lot id: block html} for the checked cards, one page-level honest line or ''). Read-only; never raises."""
    try:
        with _store():
            from mbos import decision_cases as dc
            if not dc._log().exists() or not dc.rows():
                return {}, ""
            probe = dc.propose({"listing_id": "-", "source": "gsa", "title": "", "evidence": []})
            if probe["status"] == "INTEGRITY_FAILURE":
                return {}, "Your saved decision cases failed their integrity check, so no earlier decisions are shown (nothing was applied; the file was not changed)."
            if not dc.learning_enabled():
                return {}, "Showing earlier decisions is switched off (you disabled learned use of your decision cases)."
            out = {}
            for c in cards:
                b = block(dc.propose({"listing_id": str(c["id"]), "source": "gsa", "title": c["title"], "evidence": []}))
                if b:
                    out[c["id"]] = b
            return out, ""
    except Exception:  # noqa: BLE001  (a broken private store must never break the marketplace page)
        return {}, ""


def inject(card_html: str, extra: str) -> str:
    return card_html[:-6] + extra + "</div>" if extra and card_html.endswith("</div>") else card_html
