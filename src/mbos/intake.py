"""Conversational-intake seam (ADR-0013): deterministic "what is still missing?" over per-category specs (data).

A chat/LLM front end may sit on top later; it can only call `answer()`, and basis can never be raised to `verified` here.
Nothing in this module publishes, contacts or spends.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .contracts.schemas import ContractViolation

_BASES = ("seller_stated", "system_inferred", "verified", "UNKNOWN")


def _intake_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        c = parent / "config" / "intake"
        if c.is_dir():
            return c
    packaged = Path(__file__).resolve().parent / "_data" / "config" / "intake"
    if packaged.is_dir():
        return packaged
    raise FileNotFoundError("config/intake not found")


@lru_cache(maxsize=None)
def load_spec(name: str) -> dict[str, Any]:
    return json.loads((_intake_dir() / f"{name}.v1.json").read_text())


def available() -> list[str]:
    return sorted(p.name.removesuffix(".v1.json") for p in _intake_dir().glob("*.v1.json"))


def new_draft(spec_name: str) -> dict[str, Any]:
    spec = load_spec(spec_name)
    return {"spec": spec_name, "kind": spec["kind"], "category": spec["category"], "answers": {}, "evidence": []}


def answer(draft: dict, key: str, value: Any, basis: str = "seller_stated", *, evidence: list[dict] | None = None) -> dict:
    """Record one answer. `verified` is NOT assignable here: verification needs independent evidence with provenance (inventory contract)."""
    spec = load_spec(draft["spec"])
    if key not in {f["key"] for f in spec["fields"]}:
        raise ContractViolation("intake", [f"unknown field {key!r} for spec {draft['spec']}"])
    if basis not in _BASES:
        raise ContractViolation("intake", [f"unknown basis {basis!r}"])
    if basis == "verified":
        raise ContractViolation("intake", ["basis 'verified' cannot be set by intake; it needs independent evidence with provenance"])
    if basis == "UNKNOWN":
        value = "unknown"
    out = dict(draft, answers=dict(draft["answers"]), evidence=list(draft["evidence"]))
    out["answers"][key] = {"value": value, "basis": basis}
    out["evidence"].extend(e for e in (evidence or []) if isinstance(e, dict) and e.get("kind") and e.get("ref"))
    return out


def missing(spec_name_or_draft: str | dict, draft: dict | None = None) -> list[dict]:
    """Ordered minimal questions still needed: required fields with no answer (an explicit UNKNOWN counts as answered, because the user
    said they do not know), plus any photo angle with no evidence."""
    d = draft if draft is not None else spec_name_or_draft
    assert isinstance(d, dict)
    spec = load_spec(d["spec"])
    qs = []
    for f in spec["fields"]:
        if f.get("required", True) and f["key"] not in d["answers"]:
            qs.append({"key": f["key"], "ask": f["ask"], "material": f["material"], "safety_relevant": f["safety_relevant"], "accepts_evidence": f["accepts_evidence"]})
    have = {e["ref"] for e in d["evidence"] if e.get("kind") == "photo"}
    named = " ".join(have).lower()
    for angle in spec["photo_angles"]:
        if not any(w in named for w in angle.lower().split(" / ")[0].split()):
            qs.append({"key": f"photo:{angle}", "ask": f"Can you add a photo: {angle}?", "material": False, "safety_relevant": False, "accepts_evidence": ["photo"]})
    # material and safety questions first, then spec order (stable)
    return sorted(qs, key=lambda q: (not q["safety_relevant"], not q["material"]))


def to_inventory_facts(draft: dict) -> list[dict]:
    """Facts/defect text for the canonical inventory object. Basis is carried over unchanged; nothing is upgraded."""
    spec = load_spec(draft["spec"])
    meta = {f["key"]: f for f in spec["fields"]}
    out = []
    for i, (k, a) in enumerate(draft["answers"].items(), 1):
        out.append({"id": f"f{i}", "key": k, "value": a["value"], "basis": a["basis"], "material": bool(meta[k]["material"])})
    return out
