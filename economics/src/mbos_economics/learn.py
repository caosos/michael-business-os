"""LEARN: calibration metrics and the config-bump *proposal* (research §16, gap item 6).

The engine never edits a past scorecard and never activates a config itself.
The flow is:

1. Outcomes (Outcome v1, ``predicted_vs_actual``) feed ``brier`` / ``mape``.
2. ``propose_config_bump`` builds the next config document (version bumped,
   changelog appended) and an ActionRequest draft: capability
   ``config.scoring.bump``, tier 0, reversible, ``payload_hash`` = content hash
   of the proposed config.
3. Michael decides through the Operator UI (YES/NO/MODIFY/HOLD).
4. On YES, the State lane (04) writes the new file, moves the old one to
   ``config/history/`` and emits ``CONFIG_VERSION_BUMPED`` in the same
   transaction. Historical scorecards keep replaying under their own version.
"""

from __future__ import annotations

import copy
from decimal import Decimal

from .canonical import content_hash
from .config import ScoringConfig
from .numeric import D, ZERO, fine


def brier(pairs: list[tuple[float, int]]) -> Decimal:
    """Mean squared error of probability forecasts against 0/1 outcomes."""
    if not pairs:
        raise ValueError("no forecasts")
    return fine(sum(((D(p) - D(o)) ** 2 for p, o in pairs), ZERO) / D(len(pairs)))


def mape(pairs: list[tuple[float, float]]) -> Decimal:
    """Mean absolute percentage error (actual must be non-zero)."""
    if not pairs:
        raise ValueError("no estimates")
    return fine(sum((abs(D(p) - D(a)) / abs(D(a)) for p, a in pairs), ZERO) / D(len(pairs)))


def shrink_toward_base_rate(prior: float, successes: int, n: int, prior_weight: int = 10) -> Decimal:
    """Beta-binomial style shrink: posterior = (k*prior + successes) / (k + n)."""
    if n < 0 or not 0 <= successes <= n:
        raise ValueError("invalid counts")
    return fine((D(prior_weight) * D(prior) + D(successes)) / (D(prior_weight) + D(n)))


def _bump(version: str) -> str:
    year, month, patch = version.split(".")
    return f"{year}.{month}.{int(patch) + 1}"


def _set(doc: dict, path: str, value) -> object:
    node = doc
    parts = path.split(".")
    for p in parts[:-1]:
        node = node[p]
    leaf = parts[-1]
    if leaf not in node:
        raise KeyError(f"unknown config path {path}")
    old = node[leaf]
    if isinstance(old, dict) and "value" in old:
        before, old["value"] = old["value"], value
        return before
    node[leaf] = value
    return old


def propose_config_bump(cfg: ScoringConfig, changes: dict[str, object], rationale: str,
                        evidence_refs: list[str], proposed_at: str) -> dict:
    """Return a proposal; writes nothing. ``changes`` maps dotted paths to new values."""
    if not changes:
        raise ValueError("a bump needs at least one change")
    if not evidence_refs:
        raise ValueError("a bump needs provenance (outcome / calibration ids)")
    new = copy.deepcopy(cfg.raw)
    diff = []
    for path, value in sorted(changes.items()):
        before = _set(new, path, D(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value)
        diff.append({"path": path, "from": before, "to": value})
    new_version = _bump(cfg.version)
    new["scoring_config_version"] = new_version
    new["supersedes"] = cfg.version
    new["_changelog"] = list(new.get("_changelog", [])) + [f"{new_version}: {rationale}"]
    payload_hash = content_hash(new)
    return {
        "from_version": cfg.version,
        "to_version": new_version,
        "diff": diff,
        "config": new,
        "payload_hash": payload_hash,
        "action_request_draft": {
            "category": "config",
            "capability": "config.scoring.bump",
            "tier": 0,
            "reversibility": "reversible",
            "summary": f"Bump scoring config {cfg.version} -> {new_version}: {rationale}",
            "payload_hash": payload_hash,
            "evidence_refs": sorted(evidence_refs),
            "proposed_at": proposed_at,
            "proposed_by": "agent-03-economics",
        },
    }

