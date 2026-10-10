"""A-61: owner-local decision-case store: import, readback by listingID, correction, reset/disable, proposal-first retrieval, privacy guards.
SYNTHETIC data only (no real case, amount or owner estimate): every value below is a made-up placeholder."""
import json
import os
import stat
import subprocess

import pytest

from mbos import decision_cases as dc

CASE = {"listing_id": "SYN-1001", "source": "synthetic", "title": "Synthetic dump trailer tandem axle", "decided_at": "2026-01-01T00:00:00Z", "decision": "pass",
        "reason_summary": "synthetic reason: condition unclear and exit uncertain",
        "evidence": [{"kind": "condition", "text": "synthetic condition note", "provenance": "verified"}, {"kind": "photo", "text": "synthetic photo note", "provenance": "unverified"},
                     {"kind": "cost", "text": "synthetic cost note", "provenance": "owner_estimate"}],
        "owner_estimates": [{"label": "synthetic estimate", "amount_usd": None, "note": "placeholder"}],
        "alternatives_considered": ["synthetic alternative exit"], "uncertainty": ["synthetic uncertainty"], "missing_evidence": ["synthetic missing title"],
        "owner_skills": "synthetic skills", "category_tags": ["trailer", "dump", "tandem"]}
CAND = {"listing_id": "SYN-2002", "source": "synthetic", "title": "Synthetic tandem axle dump trailer, other make", "evidence": [{"kind": "photo", "text": "x", "provenance": "unverified"}]}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_DECISION_CASES_DIR", str(tmp_path / "private"))
    return tmp_path


def write(tmp, name, obj):
    f = tmp / name
    f.write_text(json.dumps(obj))
    return f


def test_import_then_readback_by_listing_id_and_private_permissions(store):
    rows = dc.import_cases(write(store, "in.json", CASE))
    assert rows[0]["seq"] == 1 and dc.verify()[0]
    eff = dc.effective("SYN-1001")
    assert eff["active"] and eff["case"]["reason_summary"] == CASE["reason_summary"] and eff["case"]["evidence"][0]["provenance"] == "verified"
    assert eff["case"]["owner_estimates"][0]["provenance"] == "owner_estimate"
    assert stat.S_IMODE(os.stat(dc.store_dir()).st_mode) == 0o700 and stat.S_IMODE(os.stat(dc._log()).st_mode) == 0o600
    assert dc.effective("SYN-9999") is None


def test_validation_refuses_bad_cases_and_writes_nothing(store):
    bad = [{**CASE, "extra": 1}, {**CASE, "decision": "buy"}, {**CASE, "evidence": []},
           {**CASE, "owner_estimates": [{"label": "x", "provenance": "verified"}]}, {**CASE, "owner_estimates": [{"label": "x", "amount_usd": float("nan")}]},
           {**CASE, "decided_at": "yesterday"}, {**CASE, "outcome": "sold"}, {k: v for k, v in CASE.items() if k != "reason_summary"}]
    for b in bad:
        with pytest.raises(dc.CaseError):
            dc.import_cases(write(store, "b.json", b))
    with pytest.raises(dc.CaseError):                     # one bad case in a list writes none of them
        dc.import_cases(write(store, "l.json", [CASE, {**CASE, "listing_id": "SYN-1", "decision": "x"}]))
    assert dc.rows() == []


def test_duplicate_listing_must_use_correct_and_history_is_kept(store):
    dc.import_cases(write(store, "in.json", CASE))
    with pytest.raises(dc.CaseError):
        dc.import_cases(write(store, "in2.json", CASE))
    dc.correct("SYN-1001", {"decision": "watch", "uncertainty": ["synthetic revised"]}, "owner corrected the decision")
    eff = dc.effective("SYN-1001")
    assert eff["case"]["decision"] == "watch" and eff["case"]["reason_summary"] == CASE["reason_summary"]
    assert [h["kind"] for h in eff["history"]] == ["correction"] and eff["history"][0]["why"] == "owner corrected the decision"
    assert dc.rows()[0]["body"]["decision"] == "pass"                       # the original row is untouched
    with pytest.raises(dc.CaseError):
        dc.correct("SYN-1001", {"decision": "watch"}, " ")
    with pytest.raises(dc.CaseError):
        dc.correct("SYN-404", {"decision": "watch"}, "why")


def test_tampering_breaks_the_chain_and_blocks_appends(store):
    dc.import_cases(write(store, "in.json", CASE))
    p = dc._log()
    p.write_text(p.read_text().replace("synthetic reason", "edited reason"))
    assert dc.verify()[0] is False
    with pytest.raises(dc.CaseError):
        dc.outcome("SYN-1001", "x")


def test_proposal_cites_the_case_labels_estimates_and_lists_missing_evidence(store):
    dc.import_cases(write(store, "in.json", CASE))
    out = dc.propose(CAND)
    assert out["status"] == "PROPOSAL_FOR_OWNER_REVIEW" and "Not a bid" in out["authority"]
    m = out["matches"][0]
    assert m["source_case"]["listing_id"] == "SYN-1001" and m["source_case"]["case_row"] == 1
    assert {"tandem", "dump", "trailer"} <= set(m["similarity"]["shared_terms"]) or len(m["similarity"]["shared_terms"]) >= 2
    assert m["precedent_decision"] == "pass" and m["precedent_scope"].startswith("this one listing only")
    assert all(e["provenance"] == "verified" for e in m["verified_facts"]) and m["owner_estimates_not_facts"][0]["provenance"] == "owner_estimate"
    assert m["uncertainty"] and m["missing_evidence_then"] and "condition" in m["evidence_kinds_the_case_relied_on_that_the_candidate_lacks"]
    assert not any(k in json.dumps(out).lower() for k in ("bid_amount", "recommended_bid", "max_bid"))


def test_per_item_pass_is_not_a_category_dislike_and_candidate_never_matches_itself(store):
    dc.import_cases(write(store, "in.json", CASE))
    out = dc.propose({"listing_id": "SYN-3003", "title": "Synthetic laptop computer"})
    assert out["matches"] == [] and "no similar active case" in out["note"]
    assert "dislike" not in json.dumps(dc.propose(CAND)).replace("not a category dislike", "").lower()
    assert dc.propose({**CAND, "listing_id": "SYN-1001"})["matches"] == []


def test_reset_disable_enable_are_audited_and_stop_or_resume_use(store):
    dc.import_cases(write(store, "in.json", CASE))
    assert dc.propose(CAND)["matches"]
    dc.reset("SYN-1001", "owner reset this case")
    assert dc.propose(CAND)["matches"] == [] and dc.effective("SYN-1001")["active"] is False and dc.effective("SYN-1001")["case"]["decision"] == "pass"
    with pytest.raises(dc.CaseError):
        dc.reset("SYN-1001", "")
    dc.set_enabled(False, "owner switched learning off")
    assert "DISABLED" in dc.propose(CAND)["note"] and not dc.learning_enabled()
    dc.set_enabled(True, "owner switched learning on")
    assert dc.learning_enabled() and dc.verify()[0]


def test_outcomes_are_owner_reported_and_separate_from_estimates(store):
    dc.import_cases(write(store, "in.json", CASE))
    dc.outcome("SYN-1001", "synthetic: the lot closed without the owner")
    eff = dc.effective("SYN-1001")
    assert eff["outcomes"][0]["label"] == "owner_reported_actual" and eff["case"]["owner_estimates"][0]["provenance"] == "owner_estimate"
    assert dc.propose(CAND)["matches"][0]["owner_reported_outcomes"]


def test_a_store_or_import_file_that_git_could_commit_is_refused(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.setenv("MBOS_DECISION_CASES_DIR", str(repo / "cases"))
    f = repo / "in.json"
    f.write_text(json.dumps(CASE))
    with pytest.raises(dc.CaseError, match="not git-ignored"):
        dc.import_cases(f)                                                     # untracked, unignored import file
    (repo / ".gitignore").write_text("cases/\nin.json\n")
    dc.import_cases(f)                                                         # ignored: allowed
    subprocess.run(["git", "add", "-f", "in.json"], cwd=repo, check=True)
    with pytest.raises(dc.CaseError, match="TRACKED"):
        dc.import_cases(f)
    monkeypatch.setenv("MBOS_DECISION_CASES_DIR", str(repo / "visible"))
    with pytest.raises(dc.CaseError):
        dc._append("disable", None, {}, "michael", "x")                        # a store dir that is not ignored


def test_cli_prints_ids_not_contents_and_template_has_no_values(store, capsys):
    f = write(store, "in.json", CASE)
    assert dc.main(["import", str(f)]) == 0
    printed = capsys.readouterr().out
    assert "SYN-1001" in printed and "synthetic reason" not in printed
    assert dc.main(["show", "SYN-1001"]) == 0 and "synthetic reason" in capsys.readouterr().out
    assert dc.main(["verify"]) == 0 and dc.main(["show", "NOPE"]) == 1
    assert dc.main(["template"]) == 0 and "synthetic" not in capsys.readouterr().out


def test_the_default_owner_local_location_is_git_ignored_and_checked_before_any_write(monkeypatch):
    monkeypatch.delenv("MBOS_DECISION_CASES_DIR", raising=False)
    p = dc.store_dir()
    assert p == dc.ROOT / "var" / "private" / "decision_cases" and not p.exists() or p.exists()
    dc._must_be_private(p, "the case store")                                  # var/ is git-ignored in this repo: must not raise


# ---------------------------------------------------------------- A-64 corrections (synthetic data only)
def test_a64_owner_estimate_evidence_survives_retrieval_without_duplication(store):
    only_ev = {**CASE, "owner_estimates": [], "evidence": [{"kind": "cost", "text": "synthetic repair estimate text", "provenance": "owner_estimate"},
                                                           {"kind": "condition", "text": "synthetic verified condition", "provenance": "verified"}]}
    dc.import_cases(write(store, "in.json", only_ev))
    m = dc.propose(CAND)["matches"][0]
    est = m["owner_estimates_not_facts"]
    assert [e["text"] for e in est] == ["synthetic repair estimate text"] and est[0]["provenance"] == "owner_estimate" and "ESTIMATE" in est[0]["presented_as"]
    assert all(e["text"] != "synthetic repair estimate text" for e in m["verified_facts"] + m["unverified_evidence"])      # never presented as a fact


def _tamper(old, new):
    p = dc._log()
    p.write_text(p.read_text().replace(old, new))


def test_a64_corrupted_history_is_refused_everywhere_and_diagnosable(store, capsys):
    dc.import_cases(write(store, "in.json", CASE))
    _tamper("synthetic reason", "edited reason")
    for call in (lambda: dc.effective("SYN-1001"), lambda: dc.learning_enabled(), lambda: dc.correct("SYN-1001", {"decision": "watch"}, "why"),
                 lambda: dc.reset("SYN-1001", "why"), lambda: dc.import_cases(write(store, "n.json", {**CASE, "listing_id": "SYN-7"}))):
        with pytest.raises(dc.IntegrityError, match="INTEGRITY FAILURE"):
            call()
    out = dc.propose(CAND)
    assert out["status"] == "INTEGRITY_FAILURE" and out["matches"] == []
    assert dc.main(["show", "SYN-1001"]) == 3 and "INTEGRITY FAILURE" in capsys.readouterr().out
    assert dc.main(["propose", str(write(store, "c.json", CAND))]) == 3
    d = dc.diagnose()
    assert d[0]["ok"] is False and d[0]["listing_id"] == "SYN-1001" and "edited reason" not in json.dumps(d)      # inspectable, no case text
    assert "edited reason" in dc._log().read_text()                                                                   # history kept, not discarded


def test_a64_tampered_evidence_and_malformed_records_generate_no_proposal(store):
    dc.import_cases(write(store, "in.json", CASE))
    _tamper("synthetic condition note", "forged condition note")
    assert dc.propose(CAND)["status"] == "INTEGRITY_FAILURE"
    _tamper("forged condition note", "synthetic condition note")
    assert dc.verify()[0] and dc.propose(CAND)["matches"]                       # restoring the exact bytes restores validity
    with open(dc._log(), "a") as fh:
        fh.write("this is not json\n[1, 2]\n")
    assert dc.verify()[0] is False and dc.propose(CAND)["matches"] == []
    bad = [x for x in dc.diagnose() if not x["ok"]]
    assert len(bad) == 2 and all("malformed" in x["problem"] for x in bad)


def test_a64_same_listing_id_from_two_sources_stays_isolated(store):
    a = {**CASE, "source": "provider-a"}
    b = {**CASE, "source": "provider-b", "decision": "pursue", "reason_summary": "synthetic reason B", "title": "Synthetic dump trailer tandem axle B"}
    dc.import_cases(write(store, "a.json", a))
    dc.import_cases(write(store, "b.json", b))
    with pytest.raises(dc.AmbiguousListing):
        dc.effective("SYN-1001")                                                  # a bare id shared by two sources is rejected
    for call in (lambda: dc.correct("SYN-1001", {"decision": "watch"}, "why"), lambda: dc.reset("SYN-1001", "why"), lambda: dc.outcome("SYN-1001", "x")):
        with pytest.raises(dc.AmbiguousListing):
            call()
    dc.correct("SYN-1001", {"decision": "watch"}, "fix A only", source="provider-a")
    dc.outcome("SYN-1001", "synthetic outcome A", source="provider-a")
    dc.reset("SYN-1001", "reset B only", source="provider-b")
    ea, eb = dc.effective("SYN-1001", "provider-a"), dc.effective("SYN-1001", "provider-b")
    assert ea["case"]["decision"] == "watch" and ea["active"] and len(ea["outcomes"]) == 1 and [h["kind"] for h in ea["history"]] == ["correction", "outcome"]
    assert eb["case"]["decision"] == "pursue" and not eb["active"] and eb["outcomes"] == [] and [h["kind"] for h in eb["history"]] == ["reset"]
    out = dc.propose({"listing_id": "SYN-5", "title": "Synthetic tandem dump trailer"})
    assert [m["source_case"]["source"] for m in out["matches"]] == ["provider-a"]  # B is reset; A alone, with A's corrected decision
    assert out["matches"][0]["precedent_decision"] == "watch"
    assert dc.propose({"listing_id": "SYN-1001", "source": "provider-a", "title": CASE["title"]})["matches"] == []         # not itself; B is reset


def test_a64_duplicate_in_one_batch_or_existing_is_rejected_before_any_write(store):
    with pytest.raises(dc.CaseError, match="twice"):
        dc.import_cases(write(store, "d.json", [CASE, {**CASE, "reason_summary": "again"}, {**CASE, "listing_id": "SYN-2", "source": "x"}]))
    assert dc.rows() == []
    dc.import_cases(write(store, "ok.json", CASE))
    with pytest.raises(dc.CaseError, match="already exists"):
        dc.import_cases(write(store, "d2.json", [{**CASE, "listing_id": "SYN-3"}, CASE]))
    assert len(dc.rows()) == 1
    dc.import_cases(write(store, "other.json", {**CASE, "source": "other"}))                  # same id, other source: allowed
    assert len(dc.rows()) == 2 and dc.verify()[0]
