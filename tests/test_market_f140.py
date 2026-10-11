"""F-140: the precedent store is found by env, MBOS_COORDINATOR_ROOT, or the live layout <root>/var/lanes/<lane>/operator_ui. SYNTHETIC stores only."""
from __future__ import annotations

import pytest

from operator_ui import precedent_view as pv
from tests.test_market_f47 import cache, get, ui  # noqa: F401
from tests.test_market_f139 import Q, import_store, other_card


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.delenv("MBOS_DECISION_CASES_DIR", raising=False)
    monkeypatch.delenv("MBOS_COORDINATOR_ROOT", raising=False)


def make_store(ui, tmp_path, monkeypatch):
    root = tmp_path / "coord"
    store = root / "var" / "private" / "decision_cases"
    monkeypatch.setenv("MBOS_DECISION_CASES_DIR", str(store))
    import_store(tmp_path, other_card(ui)[0])
    monkeypatch.delenv("MBOS_DECISION_CASES_DIR")
    return root


def live_layout(root, monkeypatch):
    f = root / "var" / "lanes" / "agent-06" / "operator_ui" / "precedent_view.py"
    monkeypatch.setattr(pv, "__file__", str(f))        # path only; nothing is created or read there


def test_block_via_live_directory_layout(ui, tmp_path, monkeypatch):
    live_layout(make_store(ui, tmp_path, monkeypatch), monkeypatch)
    assert "data-testid='precedent'" in get(ui, **Q)


def test_block_via_coordinator_root_env(ui, tmp_path, monkeypatch):
    root = make_store(ui, tmp_path, monkeypatch)
    monkeypatch.setenv("MBOS_COORDINATOR_ROOT", str(root))
    assert "data-testid='precedent'" in get(ui, **Q)


def test_explicit_cases_dir_wins_over_layout(ui, tmp_path, monkeypatch):
    live_layout(make_store(ui, tmp_path, monkeypatch), monkeypatch)
    monkeypatch.setenv("MBOS_DECISION_CASES_DIR", str(tmp_path / "empty"))
    assert "precedent" not in get(ui, **Q)


def test_absent_store_in_live_layout_shows_nothing(ui, tmp_path, monkeypatch):
    live_layout(tmp_path / "coord", monkeypatch)
    h = get(ui, **Q)
    assert "precedent" not in h and "Your earlier decision" not in h


def test_default_store_resolution_and_env_restored(tmp_path, monkeypatch):
    assert pv._default_store() is None or "lanes" != pv.Path(pv.__file__).resolve().parents[2].name
    root = tmp_path / "r"
    (root / "var" / "private" / "decision_cases").mkdir(parents=True)
    monkeypatch.setenv("MBOS_COORDINATOR_ROOT", str(root))
    assert pv._default_store() == root / "var" / "private" / "decision_cases"
    with pv._store():
        import os
        assert os.environ["MBOS_DECISION_CASES_DIR"].endswith("decision_cases")
    assert "MBOS_DECISION_CASES_DIR" not in __import__("os").environ
