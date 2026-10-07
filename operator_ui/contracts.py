"""Validate records against the frozen v1.0.0 contracts (ADR-0004).

Uses `jsonschema` when installed. Otherwise falls back to a small Draft 2020-12
subset validator that covers every keyword the frozen contracts use (checked by
`tests/test_contracts.py`). Every row the Operator UI writes goes through
`ContractValidator.check` before commit, so a non-conforming record aborts the
whole transaction (acceptance test A10).
"""

import json
import pathlib
import re
from urllib.parse import urldefrag, urljoin

CONTRACTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "docs" / "research" / "contracts"

SCHEMA_FILES = {
    "item": "item.schema.json",
    "action_request": "action-request.schema.json",
    "approval": "approval.schema.json",
    "receipt": "receipt.schema.json",
    "provenance": "provenance.schema.json",
    "outcome": "outcome.schema.json",
}

# Keywords the fallback understands. Annotation-only keywords are ignored.
SUPPORTED = {
    "$schema", "$id", "$ref", "$defs", "title", "description", "examples", "default", "format",
    "type", "enum", "const", "required", "properties", "additionalProperties", "items",
    "minItems", "maxItems", "minimum", "maximum", "exclusiveMinimum", "minLength", "pattern",
    "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
}


class ContractError(ValueError):
    pass


def _load_all(root):
    out = {}
    for p in list(root.glob("*.schema.json")) + list(root.glob("vendor/agent-03/*.schema.json")):
        s = json.loads(p.read_text())
        out[s["$id"]] = s
    return out


def _pointer(doc, frag):
    for part in [p for p in frag.lstrip("/").split("/") if p]:
        doc = doc[part.replace("~1", "/").replace("~0", "~")]
    return doc


_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class _Mini:
    def __init__(self, by_id):
        self.by_id = by_id

    def errors(self, inst, schema, base, path="$"):
        if schema is True or schema == {}:
            return []
        if schema is False:
            return [f"{path}: schema false"]
        base = urljoin(base, schema.get("$id", "")) if "$id" in schema else base
        errs = []
        if "$ref" in schema:
            url, frag = urldefrag(urljoin(base, schema["$ref"]))
            doc = self.by_id[url] if url else self.by_id[base]
            errs += self.errors(inst, _pointer(doc, frag), url or base, path)
        t = schema.get("type")
        if t is not None:
            ts = t if isinstance(t, list) else [t]
            if not any(_TYPES[x](inst) for x in ts):
                return errs + [f"{path}: expected type {t}"]
        if "enum" in schema and inst not in schema["enum"]:
            errs.append(f"{path}: {inst!r} not in enum")
        if "const" in schema and inst != schema["const"]:
            errs.append(f"{path}: {inst!r} != const {schema['const']!r}")
        if isinstance(inst, dict):
            for k in schema.get("required", []):
                if k not in inst:
                    errs.append(f"{path}: missing required {k!r}")
            props = schema.get("properties", {})
            for k, v in inst.items():
                if k in props:
                    errs += self.errors(v, props[k], base, f"{path}.{k}")
                elif schema.get("additionalProperties") is False:
                    errs.append(f"{path}: additional property {k!r}")
                elif isinstance(schema.get("additionalProperties"), dict):
                    errs += self.errors(v, schema["additionalProperties"], base, f"{path}.{k}")
        if isinstance(inst, list):
            if "minItems" in schema and len(inst) < schema["minItems"]:
                errs.append(f"{path}: fewer than {schema['minItems']} items")
            if "maxItems" in schema and len(inst) > schema["maxItems"]:
                errs.append(f"{path}: more than {schema['maxItems']} items")
            if isinstance(schema.get("items"), dict):
                for i, v in enumerate(inst):
                    errs += self.errors(v, schema["items"], base, f"{path}[{i}]")
        if _TYPES["number"](inst):
            if "minimum" in schema and inst < schema["minimum"]:
                errs.append(f"{path}: < minimum")
            if "maximum" in schema and inst > schema["maximum"]:
                errs.append(f"{path}: > maximum")
            if "exclusiveMinimum" in schema and inst <= schema["exclusiveMinimum"]:
                errs.append(f"{path}: <= exclusiveMinimum")
        if isinstance(inst, str):
            if "minLength" in schema and len(inst) < schema["minLength"]:
                errs.append(f"{path}: shorter than minLength")
            if "pattern" in schema and not re.search(schema["pattern"], inst):
                errs.append(f"{path}: does not match {schema['pattern']}")
        for sub in schema.get("allOf", []):
            errs += self.errors(inst, sub, base, path)
        if "anyOf" in schema and not any(not self.errors(inst, s, base, path) for s in schema["anyOf"]):
            errs.append(f"{path}: matches none of anyOf")
        if "oneOf" in schema and sum(not self.errors(inst, s, base, path) for s in schema["oneOf"]) != 1:
            errs.append(f"{path}: must match exactly one of oneOf")
        if "not" in schema and not self.errors(inst, schema["not"], base, path):
            errs.append(f"{path}: matches 'not'")
        if "if" in schema:
            branch = "then" if not self.errors(inst, schema["if"], base, path) else "else"
            if branch in schema:
                errs += self.errors(inst, schema[branch], base, path)
        return errs


class ContractValidator:
    def __init__(self, root=CONTRACTS_DIR):
        self.root = pathlib.Path(root)
        self.by_id = _load_all(self.root)
        self.schemas = {k: json.loads((self.root / f).read_text()) for k, f in SCHEMA_FILES.items()}
        try:  # prefer the reference implementation when available
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource

            reg = Registry().with_resources([(i, Resource.from_contents(s)) for i, s in self.by_id.items()])
            self._impl = "jsonschema"
            self._v = {k: Draft202012Validator(s, registry=reg) for k, s in self.schemas.items()}
        except ImportError:
            self._impl = "builtin-subset"
            self._mini = _Mini(self.by_id)

    @property
    def implementation(self):
        return self._impl

    def errors(self, kind, record):
        if self._impl == "jsonschema":
            return [f"{list(e.absolute_path)}: {e.message}" for e in self._v[kind].iter_errors(record)]
        s = self.schemas[kind]
        return self._mini.errors(record, s, s["$id"])

    def check(self, kind, record):
        errs = self.errors(kind, record)
        if errs:
            raise ContractError(f"{kind} violates frozen contract: " + "; ".join(errs[:5]))
        return record
