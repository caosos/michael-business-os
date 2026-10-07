"""Repository-level guarantees: pinned contracts, no-bypass lint, CLI."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from mbos_governance.cli import main

REPO = Path(__file__).resolve().parents[1]
PINNED = {
    "action-request.schema.json": "38be3f152c69b343bddc54edc0d86d29cc9f0b8c09250e66cd5f9f49304055b3",
    "approval.schema.json": "d8593684adf1c622e7916f6e4aa068f73ff1bb38f62817f5606ce40e69072bc5",
    "provenance.schema.json": "15db68a4c6ef28d442209cd35e45970330653e7dff76ce5431bd8b05ec807b4c",
    "receipt.schema.json": "c6a55d47583541aef839bc66f5ecf07dcca187d0325b64b380a3a1bf52f155f9",
}


def test_contracts_match_frozen_v1():
    for name, digest in PINNED.items():
        data = (REPO / "src/mbos_governance/schemas" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name


def _lint():
    spec = importlib.util.spec_from_file_location("check_no_bypass", REPO / "tools/check_no_bypass.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_bypass_in_repo():
    assert _lint().violations(REPO / "src") == []


def test_no_bypass_lint_catches_violation(tmp_path):
    (tmp_path / "agent.py").write_text("import smtplib\nfrom twilio.rest import Client\nx = __import__('requests')\n")
    assert len(_lint().violations(tmp_path)) == 3


def test_cli_freeze_status_release(tmp_path, capsys):
    import shutil
    (tmp_path / "policy").mkdir()
    for f in ("policy.v1.json", "policy.schema.json"):
        shutil.copy(REPO / "policy" / f, tmp_path / "policy" / f)
    base = ["--db", str(tmp_path / "g.sqlite3"), "--policy", str(tmp_path / "policy/policy.v1.json"),
            "--panic", str(tmp_path / "panic.json")]
    assert main(base + ["panic", "status"]) == 2                        # missing => FROZEN
    assert main(base + ["panic", "init", "--actor", "michael"]) == 0
    assert main(base + ["panic", "status"]) == 2                        # init => FROZEN
    assert main(base + ["panic", "release", "--actor", "agent-07-marketing", "--reason", "x"]) == 1
    assert main(base + ["panic", "release", "--actor", "michael", "--reason", "go"]) == 0
    assert main(base + ["panic", "status"]) == 0
    assert main(base + ["panic", "freeze", "--level", "L2", "--target", "money.*", "--actor", "michael",
                        "--reason", "x"]) == 0
    assert main(base + ["panic", "freeze", "--actor", "ops", "--reason", "stop"]) == 0
    assert main(base + ["panic", "status"]) == 2
    assert main(base + ["ledger", "verify"]) == 0
    assert main(base + ["policy", "check"]) == 0
    out = capsys.readouterr().out
    assert "money.*" in out


def test_cli_freeze_works_without_database(tmp_path):
    panic = tmp_path / "panic.json"
    base = ["--db", str(tmp_path / "missing-dir" / "x" / "g.sqlite3"), "--panic", str(panic),
            "--policy", str(tmp_path / "nope.json")]
    assert main(base + ["panic", "freeze", "--actor", "michael", "--reason", "db gone"]) == 0
    assert json.loads(panic.read_text())["global"]["state"] == "FROZEN"
