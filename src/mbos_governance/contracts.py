"""Validation against the frozen v1.0.0 contracts (ADR-0004).

The schema files in ./schemas/ are byte-for-byte copies from
origin/research/agent-01-coordinator @ 1269405 (docs/research/contracts/). See
schemas/PROVENANCE.md. Validation failure is always a refusal, never a warning.
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from jsonschema import Draft202012Validator

KINDS = ("action-request", "approval", "receipt", "provenance")


class ContractViolation(ValueError):
    def __init__(self, kind: str, errors: list[str]):
        self.kind = kind
        self.errors = errors
        super().__init__(f"{kind} violates contract v1.0.0: " + "; ".join(errors))


@lru_cache(maxsize=None)
def _validator(kind: str) -> Draft202012Validator:
    if kind not in KINDS:
        raise KeyError(kind)
    text = resources.files("mbos_governance.schemas").joinpath(f"{kind}.schema.json").read_text("utf-8")
    schema = json.loads(text)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def errors(kind: str, obj: dict) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:200]}"
        for e in _validator(kind).iter_errors(obj)
    ]


def require_valid(kind: str, obj: dict) -> None:
    errs = errors(kind, obj)
    if errs:
        raise ContractViolation(kind, errs)
