"""F-139: the owner's earlier decision on a similar listing, read-only on /market cards. SYNTHETIC cases only (MBOS_DECISION_CASES_DIR in tmp)."""
from __future__ import annotations

import json
import re

import pytest

from operator_ui import market_search as ms
from tests.test_market_f47 import cache, get, post, ui  # noqa: F401
from tests.test_market_f52 import lots

Q = dict(go=1, broad=1, radius=150, max_price=100000, base="Conway AR")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setenv("MBOS_DECISION_CASES_DIR", str(tmp_path / "cases"))


def shown_ids(h):
    return re.findall(r"data-lot='([^']+)'", h.split("id='unchecked-section'")[0])


def synth_case(title_of: dict) -> dict:
    return {"listing_id": "SYN-0001", "source": "gsa", "title": "synthetic " + title_of["title"], "decided_at": "2026-01-02T00:00:00+00:00", "decision": "pass",
            "reason_summary": "SYNTHETIC reason: too much unknown repair work",
            "evidence": [{"kind": "condition", "text": "SYNTHETIC verified condition note", "provenance": "verified"},
                         {"kind": "repair_work", "text": "SYNTHETIC guess of the repair hours", "provenance": "owner_estimate"},
                         {"kind": "photo", "text": "SYNTHETIC seller photo", "provenance": "unverified"}],
            "owner_estimates": [{"label": "SYNTHETIC resale guess", "amount_usd": 987654, "note": "SYNTHETIC basis"}],
            "alternatives_considered": [], "uncertainty": ["SYNTHETIC axle unknown"], "missing_evidence": ["SYNTHETIC no title paperwork"], "owner_skills": "", "category_tags": []}


def import_store(tmp_path, first_card):
    from mbos import decision_cases as dc
    f = tmp_path / "case.json"
    f.write_text(json.dumps(synth_case(first_card)))
    dc.import_cases(f)
    return dc


def other_card(ui):                      # the case must be a DIFFERENT listing than the one shown
    cards = ms.partition(lots(), ms.parse_query({k: [str(v)] for k, v in Q.items()}))[0]
    return cards[0], cards


@pytest.mark.parametrize("view", ["gallery", "list"])
def test_match_shows_collapsed_block_with_estimates_labelled(ui, tmp_path, view):
    c0, cards = other_card(ui)
    import_store(tmp_path, c0)
    h = get(ui, view=view, **Q)
    assert h.count("data-testid='precedent'") >= 1
    blk = h.split("data-testid='precedent'")[1].split("</details>")[0]
    assert "<details" in h and "open" not in h.split("data-testid='precedent'")[0][-40:]
    assert "Your earlier decision on a similar listing (proposal, for your review)" in h
    assert "PASS" in blk and "SYNTHETIC reason" in blk
    assert "Verified facts then" in blk and "SYNTHETIC verified condition note" in blk
    assert "YOUR ESTIMATES then (estimates, not facts)" in blk and "SYNTHETIC guess of the repair hours" in blk and "SYNTHETIC resale guess" in blk
    assert blk.index("YOUR ESTIMATES") > blk.index("SYNTHETIC verified condition note") and "SYNTHETIC guess of the repair hours" not in blk.split("YOUR ESTIMATES")[0]
    assert "Uncertainty then" in blk and "Missing evidence then" in blk and "this listing lacks" in blk and "Shared words:" in blk
    assert "ONE earlier listing, not a preference for a category" in blk and "Not a bid, purchase or contact" in blk
    assert "987654" not in h                                   # a stored amount is never rendered


def test_filters_counts_and_prefs_unchanged_with_and_without_store(ui, tmp_path, monkeypatch):
    base = get(ui, **Q)
    c0, cards = other_card(ui)
    prefs_before = (tmp_path / "prefs.json").exists()
    import_store(tmp_path, c0)
    with_store = get(ui, **Q)
    assert "data-testid='precedent'" in with_store and "data-testid='precedent'" not in base
    assert shown_ids(base) == shown_ids(with_store)
    assert re.search(r"<h2>\d+ results?", base).group(0) == re.search(r"<h2>\d+ results?", with_store).group(0)
    assert (tmp_path / "prefs.json").exists() == prefs_before          # reading a precedent never writes the learned prefs
    stripped = re.sub(r"<details class='small mk-prec'.*?</details>", "", with_store, flags=re.S)
    assert re.sub(r"nonce' value='\w+'|name='nonce' value='\w+'", "", stripped) == re.sub(r"nonce' value='\w+'|name='nonce' value='\w+'", "", base)


def test_no_store_shows_nothing(ui):
    h = get(ui, **Q)
    assert "precedent" not in h and "Your earlier decision" not in h and shown_ids(h)


def test_empty_store_shows_nothing(ui, tmp_path):
    (tmp_path / "cases").mkdir()
    (tmp_path / "cases" / "cases.jsonl").write_text("")
    assert "precedent" not in get(ui, **Q)


def test_disabled_store_one_honest_line(ui, tmp_path):
    dc = import_store(tmp_path, other_card(ui)[0])
    dc.set_enabled(False, "synthetic test")
    h = get(ui, **Q)
    assert h.count("id='precedent-note'") == 1 and "switched off" in h and "data-testid='precedent'" not in h


def test_tampered_store_one_honest_line_no_crash(ui, tmp_path):
    import_store(tmp_path, other_card(ui)[0])
    p = tmp_path / "cases" / "cases.jsonl"
    p.write_text(p.read_text().replace("SYNTHETIC reason", "SYNTHETIC edited"))
    h = get(ui, **Q)
    assert h.count("id='precedent-note'") == 1 and "integrity check" in h and "SYNTHETIC" not in h and shown_ids(h)


def test_listing_never_matches_itself_and_unchecked_cards_get_no_block(ui, tmp_path):
    c0, _ = other_card(ui)
    from mbos import decision_cases as dc
    case = synth_case(c0)
    case["listing_id"] = c0["id"]
    f = tmp_path / "self.json"
    f.write_text(json.dumps(case))
    dc.import_cases(f)
    h = get(ui, **Q)
    assert f"data-lot='{c0['id']}'" in h
    unchecked = h.split("id='unchecked-section'")[1] if "id='unchecked-section'" in h else ""
    assert "data-testid='precedent'" not in unchecked
    first_card = h.split(f"data-lot='{c0['id']}'")[1].split("class='mk-g'")[0]
    assert "data-testid='precedent'" not in first_card
