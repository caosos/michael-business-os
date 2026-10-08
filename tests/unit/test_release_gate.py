"""The release gate must be able to go RED (07 G-08: F-46 contracts, F-47 test floor, F-48 stale installs, F-49 empty action path)."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load("release_gate")
pin = _load("pin_contracts")


def test_unchanged_contracts_match_their_pin():
    assert pin.diff() == []


@pytest.mark.parametrize("fault", ["edit_frozen_schema", "delete_frozen_schema", "add_unpinned_file"])
def test_a_contract_change_turns_the_pin_red(tmp_path, monkeypatch, fault):
    copy = tmp_path / "contracts"
    shutil.copytree(pin.CDIR, copy)
    monkeypatch.setattr(pin, "CDIR", copy)
    monkeypatch.setattr(pin, "MANIFEST", copy / "FROZEN.sha256.json")
    if fault == "edit_frozen_schema":
        f = copy / "approval.schema.json"
        d = json.loads(f.read_text())
        d["required"].remove("scope")  # the exact fault 07 planted: weaken Approval.required
        f.write_text(json.dumps(d, indent=2))
    elif fault == "delete_frozen_schema":
        (copy / "receipt.schema.json").unlink()
    else:
        (copy / "sneaky.schema.json").write_text("{}")
    assert pin.diff(), "a changed frozen contract must be detected"


FLOOR = json.loads((ROOT / "tools" / "release_gate_floor.json").read_text())


@pytest.mark.parametrize("out,ok", [(f"{FLOOR['min_passed']} passed in 10s", True), (f"{FLOOR['min_passed'] + 50} passed in 10s", True),
                                    (f"{FLOOR['min_passed']} skipped in 1s", False), (f"{FLOOR['min_passed'] - 1} passed in 1s", False),
                                    ("12 passed in 1s", False), (f"{FLOOR['min_passed']} passed, {FLOOR['max_skipped'] + 1} skipped in 10s", False),
                                    (f"{FLOOR['min_passed']} passed, 1 failed in 9s", False)])
def test_suite_floor_catches_skipped_shrunken_and_failing_suites(out, ok):
    assert gate.suite_floor({"ok": True, "stdout": out})["ok"] is ok


def test_a_nonzero_pytest_exit_is_red_even_with_enough_passes():
    assert gate.suite_floor({"ok": False, "stdout": "300 passed in 10s"})["ok"] is False


def test_pins_check_catches_extra_and_modified_installed_files(monkeypatch):
    mg = pytest.importorskip("mbos_governance")
    root = Path(mg.__file__).parent
    extra = root / "zz_stale_extra.py"
    extra.write_text("# stale\n")
    try:
        r = gate.pins_check()
        assert r["ok"] is False and "zz_stale_extra.py" in r["summary"]
    finally:
        extra.unlink(missing_ok=True)


def test_action_path_check_requires_real_executions():
    src = (ROOT / "tools" / "release_gate.py").read_text()
    assert 'res["effector_calls"] >= 2' in src and 'res["live_effector_calls"] == 0' in src  # F-49: not an empty check
