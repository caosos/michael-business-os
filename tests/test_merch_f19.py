"""F-19: deterministic audience views as DRY-RUN draft previews; the truthfulness lint refuses untruthful wording."""

from __future__ import annotations

import ast
import copy
import json
import re
from pathlib import Path

import pytest

from mbos import merchandising
from operator_ui import merch, merch_view
from tests.conftest import PIN  # noqa: F401
from tests.test_operator_ui import req

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / ".tools/mbos-cb55fe8/docs/research/contracts/examples/inventory"  # pinned coordinator copy (the vendored inventory schema/examples predate defect_ids_seen)
MOWER = json.loads((EX / "mower.example.json").read_text())


def check(ui, inv_path, audience="ordinary_classified", **over):
    ui.inventory_file = inv_path
    form = {"csrf": ui.csrf, "audience": audience, "headline": "Riding mower, 42 in deck, runs but smokes",
            "body": "Brand X 42T. Runs; the engine smokes blue under load. $400 or best offer.", "call_to_action": "Call or message."}
    form.update(over)
    import http.client
    from urllib.parse import urlencode

    pairs = [(k, v) for k, v in form.items() if not isinstance(v, list)] + [("disclose", d) for d in form.get("disclose", [])]
    c = http.client.HTTPConnection("127.0.0.1", ui.port, timeout=15)
    c.request("POST", "/preview/check", body=urlencode(pairs), headers={"Host": f"127.0.0.1:{ui.port}", "Content-Type": "application/x-www-form-urlencoded"})
    r = c.getresponse()
    return r.status, r.read().decode()


@pytest.fixture()
def inv_file(tmp_path):
    p = tmp_path / "inv.json"
    p.write_text(json.dumps(MOWER))
    return str(p)


def test_all_audience_views_are_deterministic_and_pass_the_lint():
    assert merch.AUDIENCES == ("ordinary_classified", "flipper", "mechanic", "parts_buyer")
    for a in merch.AUDIENCES:
        v1, v2 = merch.render_view(MOWER, a), merch.render_view(copy.deepcopy(MOWER), a)
        assert v1 == v2                                                      # templates only: byte-identical every time
        assert merchandising.lint(MOWER, v1) == [], a
        assert v1["terms"] == MOWER["terms"] and v1["inventory_hash"].startswith("sha256:")
        assert [d["text"] for d in v1["disclosures"]] == [d["text"] for d in MOWER["defects"]]     # verbatim
        assert "Engine smokes blue under load" in v1["body"]                  # the smoking defect is in every view's prose too
        assert [f["fact_id"] for f in v1["facts"]] == [f["id"] for f in MOWER["facts"]]
    assert len({merch.render_view(MOWER, a)["headline"] for a in merch.AUDIENCES}) == 4


def test_unknown_stays_unknown_and_verified_appears_only_when_it_is_true():
    v = merch.render_view(MOWER, "flipper")
    assert "Not known: hours" in v["body"] and not re.search(r"verified|inspected|certified|guaranteed", v["body"], re.I)
    inv = copy.deepcopy(MOWER)
    inv["facts"][0]["basis"] = "verified"
    inv["facts"][0]["provenance_id"] = "prov_01JA0000000000000000000009"
    mech = merch.render_view(inv, "mechanic")
    assert "(verified)" in mech["body"] and merchandising.lint(inv, mech) == []
    assert mech["facts"][0]["provenance_id"] == "prov_01JA0000000000000000000009"                  # provenance carried, not dropped


def test_a_seller_claim_that_would_overstate_condition_is_refused_not_softened():
    inv = copy.deepcopy(MOWER)
    inv["facts"][1]["value"] = "runs like new"                                                     # seller text that the lint forbids with a material defect
    with pytest.raises(merch.MerchRefused) as ei:
        merch.render_view(inv, "ordinary_classified")
    assert any("overstates condition" in r for r in ei.value.reasons)
    bad = copy.deepcopy(MOWER)
    bad["facts"][2]["value"] = "1200"                                                              # UNKNOWN basis with a value: invalid inventory
    with pytest.raises(merch.MerchRefused):
        merch.render_view(bad, "mechanic")
    with pytest.raises(merch.MerchRefused):
        merch.render_view(MOWER, "auction")                                                        # no template: refused, not improvised


def test_preview_page_is_labelled_dry_run_and_shows_facts_and_all_four_views(rt, ui, inv_file):
    ui.inventory_file = inv_file
    s, _, body = req(ui, "GET", "/preview")
    assert s == 200 and body.count("DRY-RUN draft: nothing is published") == 4 and body.count("passes lint") >= 4
    for label in ("Classified", "Project / Fix &amp; Flip", "Mechanic Special", "Parts / Donor"):
        assert label in body
    assert "Engine smokes blue under load" in body and "<b class=unk>UNKNOWN</b>" in body and "there is no generated" in body
    assert req(ui, "GET", "/preview", host="evil.example")[0] == 403


def test_a_view_that_drops_the_smoking_defect_is_refused_in_the_ui(rt, ui, inv_file):
    s, body = check(ui, inv_file, disclose=[])                                                    # the defect's checkbox is unticked
    assert s == 200 and "REFUSED: your wording is not a truthful presentation" in body
    assert "defect d1 is not disclosed" in body
    s, body = check(ui, inv_file, disclose=["d1"])                                                 # same wording, defect disclosed: passes
    assert "Passes the truthfulness lint" in body


def test_ui_refuses_overclaims_and_false_verification_with_reasons(rt, ui, inv_file):
    s, body = check(ui, inv_file, disclose=["d1"], body="Perfect condition, fully functional, no problems. $400 or best offer.")
    assert "REFUSED" in body and "prose overstates condition" in body
    s, body = check(ui, inv_file, disclose=["d1"], body="Runs; the engine smokes blue under load. Inspected and certified.")
    assert "REFUSED" in body and "claims verification of something the inventory does not have verified" in body


def test_untrusted_text_is_escaped_and_guards_hold(rt, ui, inv_file, tmp_path):
    s, body = check(ui, inv_file, disclose=["d1"], headline="<script>alert(1)</script>")
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert req(ui, "POST", "/preview/check", {"audience": "flipper"})[2].count("invalid form token") >= 1
    evil = copy.deepcopy(MOWER)
    evil["title"] = "<img src=x onerror=alert(1)>"
    p = tmp_path / "evil.json"
    p.write_text(json.dumps(evil))
    ui.inventory_file = str(p)
    assert "<img src=x" not in req(ui, "GET", "/preview")[2]


def test_missing_or_invalid_inventory_is_reported_not_previewed(rt, ui, tmp_path, monkeypatch):
    monkeypatch.delenv("MBOS_INVENTORY_FILE", raising=False)
    ui.inventory_file = None
    assert "MBOS_INVENTORY_FILE is not set" in req(ui, "GET", "/preview")[2]
    bad = copy.deepcopy(MOWER)
    bad["facts"][2]["value"] = "1200"
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    ui.inventory_file = str(p)
    out = req(ui, "GET", "/preview")[2]
    assert "not valid, so no preview is made" in out and "Classified" not in out.split("<main>")[1]


def test_no_generated_imagery_and_no_publish_path_in_the_module():
    for name in ("merch.py", "merch_view.py"):
        src = (ROOT / "operator_ui" / name).read_text()
        tree = ast.parse(src)
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not mods & {"socket", "http", "urllib", "requests", "httpx", "PIL", "openai", "anthropic", "subprocess"}, (name, mods)
        assert not re.search(r"def (publish|post|upload|generate|send)\w*\(", src)
