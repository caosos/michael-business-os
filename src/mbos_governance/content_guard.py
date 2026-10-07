"""E-04: outbound secret scan + prompt-injection tripwire (05 §14, §17 #24–26).

Rules are DATA (policy/content_rules.v1.json). The loader is fail-closed: an unreadable file, a wrong
schema or an uncompilable pattern raises ContentRulesUnavailable, and the gateway then refuses
proposals.

  secret scan  — every string in an outbound payload (recursively; keys included). A hit means
                 REFUSE. Findings carry the rule id and JSON path only, never the matched value.
  injection    — untrusted text (listing body, inbound message) and outbound payload strings. A hit
                 is a TRIPWIRE, not a wall (architecture is the wall, §14): the gateway writes an
                 INJECTION_SUSPECTED receipt, forces tier 0 + untrusted_inputs_present, marks the
                 approval request needs_review, and requires step-up on the YES.

INFERENCE: regex detection is known to be bypassable (OWASP LLM01); it is a signal on top of
capability starvation, the gate and payload-hash binding, never a substitute for them.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .ids import canonical_json, sha256_tagged

RULES_SCHEMA = "mbos.governance.content_rules/1"


class ContentRulesUnavailable(RuntimeError):
    """Rules could not be loaded. Callers MUST fail closed."""


@dataclass(frozen=True)
class Rule:
    id: str
    regex: re.Pattern
    luhn: bool = False
    scope: frozenset = frozenset({"untrusted", "payload"})


@dataclass(frozen=True)
class ContentRules:
    version: str
    secret: tuple[Rule, ...]
    injection: tuple[Rule, ...]


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str

    def as_dict(self) -> dict:
        return {"rule": self.rule, "path": self.path}


def _luhn_ok(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _compile(entries: Any, kind: str) -> tuple[Rule, ...]:
    if not isinstance(entries, list) or not entries:
        raise ContentRulesUnavailable(f"{kind} must be a non-empty list")
    out, seen = [], set()
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not isinstance(e.get("pattern"), str):
            raise ContentRulesUnavailable(f"{kind}: malformed rule {e!r:.80}")
        if e["id"] in seen:
            raise ContentRulesUnavailable(f"{kind}: duplicate id {e['id']}")
        seen.add(e["id"])
        flags = re.MULTILINE | (0 if e.get("case_sensitive") else re.IGNORECASE)
        scope = frozenset(e.get("scope", ["untrusted", "payload"]))
        if not scope or not scope <= {"untrusted", "payload"}:
            raise ContentRulesUnavailable(f"{kind}: rule {e['id']} has invalid scope {sorted(scope)}")
        try:
            out.append(Rule(e["id"], re.compile(e["pattern"], flags), bool(e.get("luhn")), scope))
        except re.error as exc:
            raise ContentRulesUnavailable(f"{kind}: rule {e['id']} does not compile: {exc}") from exc
    return tuple(out)


def load_rules(path: str | os.PathLike) -> ContentRules:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ContentRulesUnavailable(f"cannot read content rules: {exc}") from exc
    if not isinstance(data, dict) or data.get("rules_schema") != RULES_SCHEMA or not data.get("version"):
        raise ContentRulesUnavailable("content rules: wrong schema or missing version")
    digest = sha256_tagged(canonical_json(data)).split(":", 1)[1][:16]
    return ContentRules(f"{data['version']}+{digest}", _compile(data.get("secret_rules"), "secret_rules"),
                        _compile(data.get("injection_rules"), "injection_rules"))


class ContentRulesStore:
    """Re-reads on change; never serves stale rules after a failed reload (same contract as PolicyStore)."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._stamp: tuple | None = None
        self._rules: ContentRules | None = None

    def current(self) -> ContentRules:
        with self._lock:
            try:
                st = self.path.stat()
            except OSError as exc:
                self._rules = None
                raise ContentRulesUnavailable(f"content rules unreadable: {exc}") from exc
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
            if self._rules is None or stamp != self._stamp:
                self._rules = None
                self._rules = load_rules(self.path)
                self._stamp = stamp
            return self._rules


def _strings(obj: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.<key>", str(k)
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def _scan(rules: tuple[Rule, ...], obj: Any, scope: str | None = None) -> list[Finding]:
    found: list[Finding] = []
    for path, text in _strings(obj):
        for r in rules:
            if scope is not None and scope not in r.scope:
                continue
            for m in r.regex.finditer(text):
                if r.luhn and not _luhn_ok(m.group(0)):
                    continue
                found.append(Finding(r.id, path))
                break
    return found


def secret_findings(rules: ContentRules, payload: Any) -> list[Finding]:
    return _scan(rules.secret, payload)


def injection_findings(rules: ContentRules, untrusted: Any = None, payload: Any = None) -> list[Finding]:
    """Untrusted inputs get every injection rule; our own outbound payload only rules scoped to it."""
    return ([Finding(f.rule, "$.untrusted" + f.path[1:]) for f in _scan(rules.injection, untrusted or [], "untrusted")]
            + [Finding(f.rule, "$.payload" + f.path[1:]) for f in _scan(rules.injection, payload or {}, "payload")])
