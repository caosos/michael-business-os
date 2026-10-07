"""Validation against the frozen contracts (agent-01-coordinator @ 1269405, v1.0.0).

The schemas under contracts/v1.0.0 are verbatim copies; see contracts/v1.0.0/PINNED.md.
On top of the schema, the discovery lane enforces two stricter invariants (acceptance F1):
every Item has ≥1 sighting, and *every* sighting has a `raw_ref` (the schema leaves
`raw_ref` optional; we do not).
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


class ContractViolation(Exception):
    pass


@lru_cache(maxsize=1)
def _validators() -> dict[str, Draft202012Validator]:
    root = resources.files("mbos_discovery") / "contracts" / "v1.0.0"
    schemas = {}
    for entry in list(root.iterdir()) + list((root / "vendor" / "agent-03").iterdir()):
        if entry.name.endswith(".schema.json"):
            schemas[entry.name] = json.loads(entry.read_text())
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    fc = FormatChecker()
    return {name.removesuffix(".schema.json"): Draft202012Validator(s, registry=reg, format_checker=fc)
            for name, s in schemas.items()}


def errors(kind: str, obj: dict) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:300]}"
            for e in _validators()[kind].iter_errors(obj)]


def check_item(item: dict) -> None:
    errs = errors("item", item)
    if not item.get("sources"):
        errs.append("sources: Item has no sightings")
    for i, s in enumerate(item.get("sources", [])):
        if not s.get("raw_ref"):
            errs.append(f"sources/{i}/raw_ref: missing (discovery lane requires raw retention)")
    if errs:
        raise ContractViolation(f"Item {item.get('item_id')}: " + "; ".join(errs))


def check_provenance(prov: dict) -> None:
    errs = errors("provenance", prov)
    if errs:
        raise ContractViolation(f"Provenance {prov.get('provenance_id')}: " + "; ".join(errs))
