"""F-12: local daily summary, deterministic from fixtures, never sent."""

from __future__ import annotations

import ast
import copy
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("mbos_economics")

from mbos.adapters.economics import EconomicsEngineScorer  # noqa: E402
from operator_ui import summary as S  # noqa: E402
from tests.test_operator_ui import req  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "docs/research/contracts/examples"
AS_OF = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)  # 09:00 CDT → "yesterday" = 2026-10-07 local
EVIL = "<script>x</script> | **bold** [link](http://evil) # hdr"


def _scored(name, item_id, title=None, state=None):
    it = json.loads((EX / name).read_text())
    it["item_id"] = item_id
    if title:
        it["normalized"]["title"] = title
    if state:
        it["state"] = state
    r = EconomicsEngineScorer().score(it)
    it["scores"] = {"scorecard_id": r.scorecard_id or "scr_01JA0000000000000000000009", "inputs_hash": r.inputs_hash,
                    "scorecard": r.scorecard}
    return it


class FixtureStore:
    """The SpineBackend read surface, served from fixtures (no database)."""

    def __init__(self, shuffle_seed=None):
        self._items = [
            _scored("item-flip-trailer.example.json", "itm_01JA0000000000000000000001", state="AWAITING_APPROVAL"),
            _scored("item-service-drywall.example.json", "itm_01JA0000000000000000000002"),
            _scored("item-flip-trailer.example.json", "itm_01JA0000000000000000000003", title=EVIL, state="AWAITING_APPROVAL"),
        ]
        self._held = [
            {"action_request": {"action_request_id": "areq_01JA0000000000000000000011", "capability": "comms.email.send"},
             "item": self._items[0], "hold": {"hold_until": "2026-10-08T13:00:00Z", "wake_on": ["time"]},
             "held_at": "2026-10-07T13:00:00Z", "reason": "waiting on photos"},
            {"action_request": {"action_request_id": "areq_01JA0000000000000000000012", "capability": "comms.sms.send"},
             "item": self._items[2], "hold": {"hold_until": "2026-10-10T13:00:00Z", "wake_on": ["time"]},
             "held_at": "2026-10-07T15:00:00Z", "reason": EVIL},
        ]
        self._outcomes = [
            {"outcome_id": "outc_01JA0000000000000000000001", "item_id": "itm_01JA0000000000000000000001",
             "observed_at": "2026-10-07T18:00:00Z", "kind": "flip_sold", "realized": {"net_profit": 950}, "notes": EVIL},
            {"outcome_id": "outc_01JA0000000000000000000002", "item_id": "itm_01JA0000000000000000000002",
             "observed_at": "2026-10-08T04:59:59Z", "kind": "service_won", "realized": {"net_profit": 300}},   # 23:59 CDT Oct 7
            {"outcome_id": "outc_01JA0000000000000000000003", "item_id": "itm_01JA0000000000000000000002",
             "observed_at": "2026-10-08T05:00:00Z", "kind": "service_paid"},                                   # 00:00 CDT Oct 8: today
            {"outcome_id": "outc_01JA0000000000000000000004", "item_id": "itm_01JA0000000000000000000001",
             "observed_at": "2026-10-07T04:59:59Z", "kind": "flip_acquired"},                                  # Oct 6 local
        ]
        if shuffle_seed is not None:
            rnd = random.Random(shuffle_seed)
            for lst in (self._items, self._held, self._outcomes):
                rnd.shuffle(lst)

    def items_in_states(self, states):
        return [copy.deepcopy(i) for i in self._items if i["state"] in states]

    def action_requests_for_item(self, item_id):
        return []

    def held(self):
        return copy.deepcopy(self._held)

    def outcomes(self, item_id=None, limit=100):
        return copy.deepcopy(self._outcomes)

    def item(self, item_id):
        return next((copy.deepcopy(i) for i in self._items if i["item_id"] == item_id), None)


@pytest.fixture()
def health(tmp_path):
    f = tmp_path / "health.json"
    f.write_text(json.dumps({
        "ebay": {"source": "ebay", "status": "HEALTHY"},
        "craigslist": {"source": "craigslist", "status": "FROZEN", "consecutive_blocks": 2,
                       "freeze_reason": "blocked (status 403) x2 — human must clear"}}))
    t = AS_OF.timestamp() - 3600
    os.utime(f, (t, t))
    return str(f)


def test_deterministic_bytes_and_order_invariant(health):
    a = S.build_summary(FixtureStore(), AS_OF, health_file=health)
    b = S.build_summary(FixtureStore(), AS_OF, health_file=health)
    c = S.build_summary(FixtureStore(shuffle_seed=7), AS_OF, health_file=health)
    assert a == b and a["summary_hash"] == c["summary_hash"]
    assert S.render_markdown(a) == S.render_markdown(c) and S.render_html_document(a) == S.render_html_document(c)
    assert S.build_summary(FixtureStore(), AS_OF.replace(hour=15), health_file=health)["summary_hash"] != a["summary_hash"]


def test_sections_content(health):
    s = S.build_summary(FixtureStore(), AS_OF, health_file=health)
    assert s["local_date"] == "2026-10-08"
    ranked = [r["item_id"] for r in s["digest"]["rows"]]
    assert set(ranked) == {"itm_01JA0000000000000000000001", "itm_01JA0000000000000000000002", "itm_01JA0000000000000000000003"}
    assert [r["rank"] for r in s["digest"]["rows"]] == [1, 2, 3]
    assert [h["overdue"] for h in s["holds"]] == [True, False]  # overdue first
    assert [o["outcome_id"][-1] for o in s["outcomes"]["rows"]] == ["1", "2"] and s["outcomes"]["net_profit"] == 1250
    assert s["sources"]["stale"] is False and [r["status"] for r in s["sources"]["rows"]][0] == "FROZEN"
    md = S.render_markdown(s)
    assert "## HOLD backlog (2, 1 overdue)" in md and "**OVERDUE**" in md and "net $1,250" in md
    assert "craigslist" in md and "human must clear" in md and "Generated locally, never sent" in md


def test_stale_health_and_missing_digest_engine(health, monkeypatch):
    s = S.build_summary(FixtureStore(), datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc), health_file=health)
    assert s["sources"]["stale"] is True and "STALE" in S.render_markdown(s)
    import sys

    monkeypatch.setitem(sys.modules, "mbos_economics.digest", None)
    s = S.build_summary(FixtureStore(), AS_OF, health_file=health)
    assert "Digest unavailable" in S.render_markdown(s) and "Digest unavailable" in S.render_html_body(s)


def test_untrusted_text_escaped_in_markdown_and_html(health):
    s = S.build_summary(FixtureStore(), AS_OF, health_file=health)
    md, doc = S.render_markdown(s), S.render_html_document(s)
    assert "<script>" not in md and "<script>" not in doc
    assert "](http://evil)" not in md and "**bold**" not in md
    hold_rows = [ln for ln in md.splitlines() if ln.startswith("| ") and ("OVERDUE" in ln or "| waiting |" in ln)]
    assert len(hold_rows) == 2
    for line in hold_rows:  # escaped pipes cannot add table columns: 5 columns → 6 unescaped pipes
        assert line.count("|") - line.count("\\|") == 6, line


def test_write_files_local_and_atomic(health, tmp_path):
    s = S.build_summary(FixtureStore(), AS_OF, health_file=health)
    out = tmp_path / "out"
    paths = S.write_files(s, out)
    assert sorted(Path(p).name for p in paths.values()) == ["daily-summary-2026-10-08.html", "daily-summary-2026-10-08.md"]
    assert Path(paths["md"]).read_text() == S.render_markdown(s)
    assert not [p for p in out.iterdir() if p.name.startswith(".tmp-")]
    S.write_files(s, out)  # idempotent overwrite
    assert len(list(out.iterdir())) == 2


def test_summary_module_has_no_network_or_send_path():
    src = (ROOT / "operator_ui" / "summary.py").read_text()
    tree = ast.parse(src)
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not mods & {"socket", "http", "urllib", "smtplib", "ssl", "requests", "httpx", "telnyx", "twilio", "subprocess", "comms_spec"}
    assert "def send" not in src


def test_ui_page_and_cli_on_the_real_spine(rt, discover, ui, tmp_path):
    from operator_ui.__main__ import main

    discover("FIX-TRAILER-1")
    s, _, body = req(ui, "GET", "/summary")
    assert s == 200 and "MBOS daily summary" in body and "Generated locally, never sent" in body
    assert req(ui, "GET", "/summary", host="evil.example")[0] == 403
    assert main(["summary", "--out-dir", str(tmp_path / "ds"), "--as-of", "2026-10-08T14:00:00Z", "--top", "5"]) == 0
    files = sorted(p.name for p in (tmp_path / "ds").iterdir())
    assert files == ["daily-summary-2026-10-08.html", "daily-summary-2026-10-08.md"]
