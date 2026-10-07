"""Load, validate and look up a versioned ``scoring-config.json``.

The current config is ``economics/config/scoring-config.json``; superseded
versions live in ``economics/config/history/scoring-config-<version>.json`` so a
historical scorecard can be replayed under the version that produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .canonical import content_hash
from .numeric import ONE

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

_META_KEYS = {"basis", "note", "source"}

# Versions whose structure this engine can execute. 2026.10.0 stored formulas as
# prose strings and has no executable form; it is archived for the record only.
EXECUTABLE_VERSIONS = {"2026.10.1"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ScoringConfig:
    version: str
    raw: dict = field(repr=False)
    hash: str = ""

    def get(self, path: str) -> Any:
        """Value at a dotted path. ``{value: x, ...}`` leaves unwrap to ``x``."""
        node: Any = self.raw
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(f"missing config key {path!r} in {self.version}")
            node = node[part]
        if isinstance(node, dict) and "value" in node:
            node = node["value"]
        return node

    def num(self, path: str) -> Decimal:
        v = self.get(path)
        if not isinstance(v, Decimal):
            raise ConfigError(f"{path} is not a number")
        return v

    def group(self, path: str) -> dict[str, Decimal]:
        """A ``{name: number}`` group, dropping basis/note/_* metadata."""
        node = self.get(path)
        if not isinstance(node, dict):
            raise ConfigError(f"{path} is not a group")
        return {k: v for k, v in node.items() if k not in _META_KEYS and not k.startswith("_")}


def _parse(text: str) -> dict:
    return json.loads(text, parse_float=Decimal, parse_int=Decimal)


def _validate(cfg: ScoringConfig) -> None:
    if cfg.version not in EXECUTABLE_VERSIONS:
        raise ConfigError(f"scoring_config_version {cfg.version} is not executable by this engine")
    for lane in ("flip", "service"):
        w = cfg.group(f"composite_weights.{lane}")
        if set(w) != {"ev", "pph", "roi", "ttc", "risk", "conf", "skill", "scarcity"}:
            raise ConfigError(f"composite_weights.{lane} has wrong keys")
        if sum(w.values()) != ONE:
            raise ConfigError(f"composite_weights.{lane} must sum to 1")
        e = cfg.group(f"confidence.{lane}_evidence_weights")
        if sum(e.values()) != ONE:
            raise ConfigError(f"confidence.{lane}_evidence_weights must sum to 1")
    for g in ("risk_score_weights", "scarcity_weights"):
        if sum(cfg.group(g).values()) != ONE:
            raise ConfigError(f"{g} must sum to 1")
    for p, v in cfg.group("skills.proficiency").items():
        if not (0 <= v <= 1):
            raise ConfigError(f"skills.proficiency.{p} out of [0,1]")


def load_config_file(path: Path) -> ScoringConfig:
    raw = _parse(path.read_text(encoding="utf-8"))
    version = raw.get("scoring_config_version")
    if not isinstance(version, str):
        raise ConfigError(f"{path} has no scoring_config_version")
    cfg = ScoringConfig(version=version, raw=raw, hash=content_hash(raw))
    _validate(cfg)
    return cfg


def load_config(version: str | None = None, config_dir: Path = CONFIG_DIR) -> ScoringConfig:
    """Load the current config, or a specific version from current/history."""
    current = config_dir / "scoring-config.json"
    if version is None:
        return load_config_file(current)
    candidates = [current, config_dir / "history" / f"scoring-config-{version}.json"]
    for p in candidates:
        if p.exists():
            raw_version = json.loads(p.read_text(encoding="utf-8")).get("scoring_config_version")
            if raw_version == version:
                return load_config_file(p)
    raise ConfigError(f"scoring_config_version {version} not found in {config_dir}")
