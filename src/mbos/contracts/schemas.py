"""Loads the FROZEN v1.0.0 contracts from `docs/research/contracts/` (ADR-0004).

The JSON Schemas there are the single source of truth. This module never copies
or edits them: code validates against the files as committed. Changing a
contract means a new contract version and an ADR, never an edit here.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

CONTRACT_VERSION = "1.0.0"
KINDS = ("item", "action-request", "approval", "receipt", "provenance", "outcome")


class ContractViolation(ValueError):
    def __init__(self, kind: str, errors: list[str]):
        self.kind = kind
        self.errors = errors
        super().__init__(f"{kind} violates frozen contract v{CONTRACT_VERSION}: " + "; ".join(errors[:5]))


def contracts_dir() -> Path:
    env = os.environ.get("MBOS_CONTRACTS_DIR")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "research" / "contracts"
        if (candidate / "item.schema.json").exists():
            return candidate
    raise FileNotFoundError("docs/research/contracts not found; set MBOS_CONTRACTS_DIR")


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, dict[str, Any]], Registry]:
    root = contracts_dir()
    schemas: dict[str, dict[str, Any]] = {}
    for p in sorted(root.glob("*.schema.json")) + sorted(root.glob("vendor/agent-03/*.schema.json")):
        s = json.loads(p.read_text())
        Draft202012Validator.check_schema(s)
        schemas[p.name.removesuffix(".schema.json")] = s
    registry = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    return schemas, registry


def schema(kind: str) -> dict[str, Any]:
    return _load()[0][kind]


@lru_cache(maxsize=None)
def validator(kind: str) -> Draft202012Validator:
    schemas, registry = _load()
    return Draft202012Validator(schemas[kind], registry=registry, format_checker=FormatChecker())


def errors(kind: str, doc: Any) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:300]}"
        for e in validator(kind).iter_errors(doc)
    ]


def validate(kind: str, doc: Any) -> None:
    errs = errors(kind, doc)
    if errs:
        raise ContractViolation(kind, errs)
