import sys
import types

from mbos.adapters.economics import EconomicsEnricher


def _install(monkeypatch, fn):
    mod = types.ModuleType("mbos_discovery.model_years")
    mod.extract_model_years = fn
    pkg = types.ModuleType("mbos_discovery")
    monkeypatch.setitem(sys.modules, "mbos_discovery", pkg)
    monkeypatch.setitem(sys.modules, "mbos_discovery.model_years", mod)


def test_title_years_are_extracted_by_lane_b_when_installed(monkeypatch):
    _install(monkeypatch, lambda t: [{"year": 2018, "evidence": "MY2018", "basis": "INFERENCE"}])
    assert EconomicsEnricher._model_years({"normalized": {"title": "MY2018 Cub Cadet"}}) == [{"year": 2018, "evidence": "MY2018", "basis": "INFERENCE"}]


def test_nothing_found_or_extractor_error_or_missing_package_degrades_to_none(monkeypatch):
    _install(monkeypatch, lambda t: [])
    assert EconomicsEnricher._model_years({"normalized": {"title": "Cub Cadet"}}) is None

    def boom(t):
        raise RuntimeError("bug")

    _install(monkeypatch, boom)
    assert EconomicsEnricher._model_years({"normalized": {"title": "x"}}) is None
    monkeypatch.setitem(sys.modules, "mbos_discovery", None)     # ImportError on import
    assert EconomicsEnricher._model_years({"normalized": {"title": "x"}}) is None
    assert EconomicsEnricher._model_years({}) is None
