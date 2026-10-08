"""Model router (ADR-0014): pure, deterministic, data-driven. Decides which Claude model alias a bounded worker uses and why.

Rules live in `config/model_router.v1.json`. First matching rule wins. Every decision is returned with its rule id and reason so it
can be recorded in telemetry (the "routing receipt"). Aliases are resolved by the Claude Code CLI; nothing here names a model id.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

TASK_KINDS = ("implement", "test", "docs", "adapter", "research", "plan", "architecture", "integration", "debug", "review",
              "migration", "synthesis", "deep_research", "classification", "extraction")


@dataclass(frozen=True)
class TaskProfile:
    task_id: str
    lane: str
    kind: str = "implement"
    risk: str = "medium"          # low | medium | high
    cross_lane: bool = False
    long_horizon: bool = False
    prior_failures: int = 0


@dataclass(frozen=True)
class Route:
    model: str                    # CLI alias, e.g. "sonnet"
    tier: str                     # default | planning | hardest | cheap
    rule_id: str
    reason: str
    max_turns: int
    escalate_to: Optional[str] = None
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _config_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        c = parent / "config" / "model_router.v1.json"
        if c.exists():
            return c
    p = Path(__file__).resolve().parent / "_data" / "config" / "model_router.v1.json"
    if p.exists():
        return p
    raise FileNotFoundError("config/model_router.v1.json not found")


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(_config_path().read_text())


def _matches(cond: dict, t: TaskProfile) -> bool:
    for k, v in cond.items():
        if k == "kind_in" and t.kind not in v:
            return False
        if k == "risk" and t.risk != v:
            return False
        if k == "long_horizon" and t.long_horizon is not v:
            return False
        if k == "cross_lane" and t.cross_lane is not v:
            return False
        if k == "prior_failures_gte" and t.prior_failures < v:
            return False
        if k == "any_of" and not any(_matches(c, t) for c in v):
            return False
    return True


def route(t: TaskProfile, policy: Optional[dict] = None, *, available: Optional[set[str]] = None) -> Route:
    """Pick the model. `available` is the set of aliases confirmed usable (probe); a missing alias falls back, with a note."""
    if t.kind not in TASK_KINDS:
        raise ValueError(f"unknown task kind {t.kind!r}; expected one of {TASK_KINDS}")
    if t.risk not in ("low", "medium", "high"):
        raise ValueError(f"unknown risk {t.risk!r}")
    p = policy or load_policy()
    aliases, d = p["aliases"], p["defaults"]
    for rule in p["rules"]:
        if not _matches(rule["if"], t):
            continue
        tier, notes = rule["model"], []
        esc = rule.get("escalate_to")
        if esc == "hardest" and not t.long_horizon:
            esc = None  # Fable is never an automatic escalation for non-long-horizon work
        model = aliases[tier]
        if available is not None and model not in available:
            fb = rule.get("fallback") or "default"
            notes.append(f"alias {model!r} unavailable; fell back to {aliases[fb]!r}")
            tier, model = fb, aliases[fb]
        turns = min(d["max_turns"] + (20 if t.risk == "high" else 0), d["max_turns_cap"])
        return Route(model=model, tier=tier, rule_id=rule["id"], reason=rule["why"], max_turns=turns,
                     escalate_to=aliases.get(esc) if esc else None, notes=notes)
    raise RuntimeError("router policy has no catch-all rule")


def escalate(current: Route, t: TaskProfile, policy: Optional[dict] = None) -> Optional[Route]:
    """Next model after a failed attempt, or None when already at the top allowed for this task."""
    p = policy or load_policy()
    ladder = p["escalation"]["ladder"]
    if current.tier not in ladder:
        return None
    i = ladder.index(current.tier)
    nxt = ladder[i + 1] if i + 1 < len(ladder) else None
    if nxt is None or (nxt == "hardest" and not t.long_horizon):
        return None
    alias = p["aliases"][nxt]
    return Route(model=alias, tier=nxt, rule_id="ESCALATE", reason=f"escalated from {current.model} after a failed attempt",
                 max_turns=current.max_turns)
