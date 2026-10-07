"""B-19: `mbos-discover run` covers every source; --source works for each with --fixtures; --dry prints the exact
requests; and nothing touches the network (or a mailbox) without the live flag."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest

from conftest import FIX
from mbos_discovery.cli import main
from mbos_discovery.runner import ALL_SOURCES

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "discovery.example.toml"


@pytest.fixture
def work(tmp_path, monkeypatch):
    shutil.copytree(FIX / "intake", tmp_path / "var" / "intake")
    shutil.copytree(FIX / "comps" / "manual", tmp_path / "var" / "comps" / "manual")
    for d in ("govdeals", "publicsurplus", "estatesales"):
        shutil.copytree(FIX / "email", tmp_path / "var" / "mail" / d)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any attempt to reach the network, a mailbox or a real HTTP transport fails the test."""
    def boom(*a, **k):
        raise AssertionError("network/mailbox access attempted")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    import imaplib
    monkeypatch.setattr(imaplib.IMAP4_SSL, "__init__", boom)
    from mbos_discovery.http import UrllibTransport
    monkeypatch.setattr(UrllibTransport, "request", boom)


def _run(args, capsys):
    rc = main(args)
    return rc, capsys.readouterr().out


def test_every_source_runs_green_from_fixtures(work, capsys):
    for src in ALL_SOURCES:
        if src == "ebay_browse_asking":
            continue                       # derived: covered below (needs eBay items first)
        rc, out = _run(["--data-dir", "d-" + src, "run", "--config", str(CFG), "--fixtures", str(FIX), "--source", src], capsys)
        assert rc == 0, (src, out)
        assert src in out and " error " not in out and "skipped" not in out, (src, out)


def test_fixture_results_are_the_adapter_results(work, capsys):
    cases = {"govdeals_email": "fetched=3 new=2", "samgov": "fetched=5 new=4", "manual": "added=6",
             "ebay_marketplace_insights": "added=3", "cpsc_recalls": "records=6 entries=3 review=3"}
    for src, expect in cases.items():
        _, out = _run(["--data-dir", "r-" + src, "run", "--config", str(CFG), "--fixtures", str(FIX), "--source", src], capsys)
        assert expect in out, (src, out)


NHTSA_CFG = '''[[profile]]
id = "kb-nhtsa"
source = "nhtsa"
vehicles = [{ make = "FIXMOTORS", model = "ROADSTER", year = 2012 }, { make = "FIXMOTORS", model = "3", year = 2012 }]
'''


def test_nhtsa_fixture_vehicles_from_config(work, capsys, tmp_path):
    cfg = tmp_path / "nhtsa.toml"
    cfg.write_text(NHTSA_CFG)
    _, out = _run(["--data-dir", "nh", "run", "--config", str(cfg), "--fixtures", str(FIX)], capsys)
    assert "records=6" in out and "entries=0" in out
    k = json.loads((work / "nh" / "knowledge" / "nhtsa.json").read_text())
    assert len(k["records"]) == 6 and k["entries"] == []        # 4 recalls + 2 complaint queries; all held for review


def test_asking_comps_derive_from_stored_items_without_requests(work, capsys):
    base = ["--data-dir", "ask", "run", "--config", str(CFG), "--fixtures", str(FIX)]
    _run(base + ["--source", "ebay"], capsys)
    rc, out = _run(base + ["--source", "ebay_browse_asking"], capsys)
    assert rc == 0 and "asking comps=" in out
    comps = json.loads((work / "ask" / "comps.json").read_text())["comps"]
    assert comps and all(c["kind"] == "asking" and "sold_date" not in c for c in comps.values())


def test_knowledge_outputs_are_written_and_entries_are_review_gated(work, capsys):
    cfg = work / "both.toml"
    cfg.write_text(CFG.read_text().split("[[profile]]\nid = \"kb-nhtsa\"")[0] + NHTSA_CFG)
    _run(["--data-dir", "k", "run", "--config", str(cfg), "--fixtures", str(FIX), "--source", "cpsc_recalls", "--source", "nhtsa"], capsys)
    cpsc = json.loads((work / "k" / "knowledge" / "cpsc_recalls.json").read_text())
    assert len(cpsc["entries"]) == 3 and len(cpsc["review"]) == 3
    nhtsa = json.loads((work / "k" / "knowledge" / "nhtsa.json").read_text())
    assert nhtsa["entries"] == [] and any("model-year" in r["reason"] for r in nhtsa["review"])   # held until years


def test_dry_lists_exact_requests_for_every_network_source(work, capsys):
    rc, out = _run(["run", "--config", str(CFG), "--dry"], capsys)
    assert rc == 0
    assert "POST https://api.ebay.com/identity/v1/oauth2/token" in out
    assert "GET  https://api.ebay.com/buy/browse/v1/item_summary/search?q=utility+trailer" in out
    assert "marketplace_insights/v1_beta/item_sales/search" in out
    assert "GET  https://api.gsa.gov/assets/gsaauctions/v2/auctions?format=JSON" in out
    assert "https://api.sam.gov/opportunities/v2/search?" in out and "api_key=" not in out      # keys never printed
    assert "https://trashnothing.com/api/v1.4/posts?" in out
    assert "https://www.saferproducts.gov/RestWebServices/Recall?format=json&ProductName=mower" in out
    assert "https://api.nhtsa.gov/recalls/recallsByVehicle?make=ACURA&model=RDX&modelYear=2012" in out
    assert "https://api.nhtsa.gov/complaints/complaintsByVehicle?make=ACURA&model=RDX&modelYear=2012" in out
    assert "DRY-RUN-PLACEHOLDER" not in out and "Basic " not in out and "client_secret=" not in out
    assert "live flag OFF → a real run makes 0 requests" in out
    assert "reads local .eml files" in out and "derived from eBay listings already stored" in out
    assert not (work / "var" / "discovery").exists()                       # --dry writes no state
    assert not list(work.glob("*/health.json"))


def test_dry_shows_the_read_only_imap_sequence(work, capsys, tmp_path):
    cfg = tmp_path / "imap.toml"
    cfg.write_text('''[[profile]]
id = "m"
source = "govdeals_email"
lane = "flip"
imap = { host = "imap.example.invalid", user = "a@example.invalid", password_env = "NOPE_PW", folder = "INBOX", live = false }
''')
    rc, out = _run(["run", "--config", str(cfg), "--dry"], capsys)
    assert rc == 0
    for line in ("connect IMAP4_SSL imap.example.invalid", "LOGIN a@example.invalid ***", "EXAMINE INBOX  (read-only: True)", "SEARCH SINCE"):
        assert line in out
    assert "STORE" not in out and "EXPUNGE" not in out and "NOPE_PW: NOT set" in out.replace("env ", "")


def test_without_live_flags_a_real_run_never_touches_the_network(work, capsys, monkeypatch):
    for k in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "GSA_API_KEY", "TRASHNOTHING_API_KEY", "SAMGOV_API_KEY", "MBOS_PANIC_STATE"):
        monkeypatch.delenv(k, raising=False)
    rc, out = _run(["--data-dir", "nolive", "run", "--config", str(CFG)], capsys)   # no --fixtures, no live flags
    assert rc == 0                                                                  # (no_network fixture would raise)
    for src in ("gsa_auctions", "samgov", "trashnothing", "cpsc_recalls", "nhtsa", "ebay_marketplace_insights"):
        assert any(l.startswith(src) and "error" in l for l in out.splitlines()), (src, out)
    assert any(l.startswith("ebay ") and "not set" in l for l in out.splitlines())


def test_bad_config_and_unknown_source_exit_2(work, capsys, tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[[profile]]\nid = "x"\nsource = "nextdoor"\nlane = "flip"\n')
    with pytest.raises(SystemExit):
        main(["run", "--config", str(bad), "--source", "nextdoor"])                  # not a choice
    rc, _ = _run(["run", "--config", str(bad)], capsys)
    assert rc == 2
