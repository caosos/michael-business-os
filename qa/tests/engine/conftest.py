"""G-10 engine half: lane C's scoring engine from the pinned commit (qa/impl_lane_pins.json `lane_c_03_engine`), extracted with
`git archive` into a temp dir and imported from there. Nothing is installed into the venv."""
from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys
import tarfile

import pytest

QA = pathlib.Path(__file__).resolve().parents[2]
REPO = QA.parent


@pytest.fixture(scope="session")
def eco(tmp_path_factory):
    sha = json.loads((QA / "impl_lane_pins.json").read_text())["lane_c_03_engine"]
    out = tmp_path_factory.mktemp("eco")
    tar = subprocess.run(["git", "archive", sha, "economics"], cwd=REPO, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(out, filter="data")
    root = out / "economics"
    sys.path[:0] = [str(root / "src"), str(root / "tests")]
    import importlib

    for m in [m for m in sys.modules if m.startswith("mbos_economics")]:
        del sys.modules[m]
    ns = type("Eco", (), {})()
    ns.root = root
    ns.cfg = importlib.import_module("mbos_economics.config").load_config()
    ns.engine = importlib.import_module("mbos_economics.engine")
    ns.cases = importlib.import_module("class_cases")
    ns.scored_at = importlib.import_module("worked_cases").SCORED_AT
    ns.InputError = importlib.import_module("mbos_economics.inputs").InputError
    yield ns


def score(eco, name, mutate=None, cfg=None):
    it = eco.cases.fresh(name)
    if mutate:
        mutate(it["economics"])
    return eco.engine.score_item(it, cfg or eco.cfg, eco.scored_at)["scores"]["scorecard"]


def with_profile_cash(eco, value):
    """C-23: current cash comes only from Michael's profile, mirrored into config `operator_context.current_cash`."""
    import copy
    import dataclasses
    from decimal import Decimal

    raw = copy.deepcopy(eco.cfg.raw)
    raw["operator_context"]["current_cash"]["value"] = Decimal(value)
    return dataclasses.replace(eco.cfg, raw=raw)


@pytest.fixture(scope="session")
def mc():
    import importlib

    from mbos_qa import pincheck

    pincheck.require()
    return importlib.import_module("mbos.card")


@pytest.fixture(scope="session")
def profile(mc):
    return mc.load_profile()
