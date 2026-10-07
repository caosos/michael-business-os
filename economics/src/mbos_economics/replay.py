"""Deterministic replay (AT-1, C22): re-score a stored scorecard and compare.

Replay loads the *stored* ``scoring_config_version`` (current file or history),
re-derives the engine input from the Item, re-runs the engine at the stored
``computed_at`` and requires byte-identical canonical output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__ as ENGINE_VERSION
from .canonical import canonical_json
from .config import CONFIG_DIR, load_config
from .engine import score
from .inputs import build_engine_input


def _diff(a: Any, b: Any, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else k
            if k not in a or k not in b:
                out.append(f"{p}: present only in {'stored' if k in a else 'replayed'}")
            else:
                out += _diff(a[k], b[k], p)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _diff(x, y, f"{path}[{i}]")]
    return [] if canonical_json(a) == canonical_json(b) else [f"{path}: stored={a!r} replayed={b!r}"]


def replay_item(item: dict, config_dir: Path = CONFIG_DIR) -> dict:
    stored = item["scores"]
    sc = stored["scorecard"]
    cfg = load_config(sc["scoring_config_version"], config_dir)
    notes = []
    if sc.get("config_hash") and sc["config_hash"] != cfg.hash:
        notes.append("config content differs from the content that produced the scorecard "
                     "(a value was changed without a version bump)")
    if sc.get("engine_version") and sc["engine_version"] != ENGINE_VERSION:
        notes.append(f"engine {sc['engine_version']} produced it; replaying with {ENGINE_VERSION}")
    fresh = score(build_engine_input(item), cfg, sc["computed_at"])
    diffs = _diff(sc, fresh["scorecard"])
    result = {
        "inputs_hash_match": fresh["inputs_hash"] == stored["inputs_hash"],
        "scorecard_id_match": fresh["scorecard_id"] == stored["scorecard_id"],
        "scorecard_match": not diffs,
        "diffs": diffs,
        "notes": notes,
    }
    result["match"] = result["inputs_hash_match"] and result["scorecard_id_match"] and result["scorecard_match"]
    return result
