"""Contract validation runner over the pinned, frozen contracts v1.0.0 (ADR-0004).

Stricter than Agent 01's validate_contracts.py in two ways (both additive, never weaker):
  * `format` keywords (date-time) are enforced via FormatChecker.
  * the pin manifest is verified byte-for-byte before anything is validated.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import subprocess
from dataclasses import dataclass, field

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "contracts"
KINDS = ("item", "action-request", "approval", "receipt", "provenance", "outcome")
EXAMPLE_PREFIX = {
    "item-": "item", "action-request-": "action-request", "approval-": "approval",
    "receipt-": "receipt", "provenance-": "provenance", "outcome-": "outcome",
}


class ContractViolation(Exception):
    def __init__(self, kind: str, errors: list[str]):
        super().__init__(f"{kind} violates contract: " + "; ".join(errors[:5]))
        self.kind = kind
        self.errors = errors


class Contracts:
    def __init__(self, root: pathlib.Path = CONTRACTS_DIR):
        self.root = root
        self.pin = json.loads((root / "PIN.json").read_text())
        self.schemas: dict[str, dict] = {}
        for p in sorted(root.glob("*.schema.json")) + sorted(root.glob("vendor/agent-03/*.schema.json")):
            s = json.loads(p.read_text())
            Draft202012Validator.check_schema(s)
            self.schemas[p.name] = s
        self.registry = Registry().with_resources(
            [(s["$id"], Resource.from_contents(s)) for s in self.schemas.values()]
        )
        self._validators = {
            k: Draft202012Validator(
                self.schemas[f"{k}.schema.json"], registry=self.registry,
                format_checker=Draft202012Validator.FORMAT_CHECKER,
            )
            for k in KINDS
        }

    @property
    def version(self) -> str:
        return self.pin["contracts_version"]

    def errors(self, kind: str, doc: dict) -> list[str]:
        return [
            f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:200]}"
            for e in self._validators[kind].iter_errors(doc)
        ]

    def check(self, kind: str, doc: dict) -> None:
        errs = self.errors(kind, doc)
        if errs:
            raise ContractViolation(kind, errs)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ContractReport:
    pin_commit: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _example(root: pathlib.Path, name: str) -> dict:
    return json.loads((root / "examples" / name).read_text())


def negative_cases(root: pathlib.Path) -> list[tuple[str, str, dict]]:
    """(name, kind, doc) — every doc MUST be rejected. First four mirror Agent 01's validator."""
    ar = _example(root, "action-request-email-held.example.json")
    rc = _example(root, "receipt-approval-decided.example.json")
    flip = _example(root, "item-flip-trailer.example.json")
    svc = _example(root, "item-service-drywall.example.json")
    ap = _example(root, "approval-hold.example.json")
    pv = _example(root, "provenance-human.example.json")
    cases = []

    def mut(name, kind, base, fn):
        d = copy.deepcopy(base)
        fn(d)
        cases.append((name, kind, d))

    mut("irreversible action at tier 1", "action-request", ar, lambda d: d.update(tier=1))
    mut("receipt without provenance", "receipt", rc, lambda d: d.update(provenance_ids=[]))
    mut("flip with service category", "item", flip, lambda d: d.update(category="drywall_repair"))
    mut("service with flip economics", "item", svc, lambda d: d.update(economics=copy.deepcopy(flip["economics"])))
    # QA-lane additions
    mut("money action at tier 2", "action-request", ar,
        lambda d: d.update(category="money", reversibility="reversible", untrusted_inputs_present=False, tier=2))
    mut("untrusted input at tier 1", "action-request", ar,
        lambda d: d.update(reversibility="reversible", untrusted_inputs_present=True, tier=1))
    mut("action request without provenance", "action-request", ar, lambda d: d.update(provenance_ids=[]))
    mut("unprefixed areq id", "action-request", ar, lambda d: d.update(action_request_id="01JA0000000000000000000001"))
    mut("MODIFY without modifications", "approval", ap, lambda d: (d.update(decision="MODIFY"), d.pop("hold")))
    mut("HOLD without hold block", "approval", ap, lambda d: d.pop("hold"))
    mut("NO without reason", "approval", ap, lambda d: (d.update(decision="NO"), d.pop("hold")))
    mut("decision outside YES/NO/MODIFY/HOLD", "approval", ap, lambda d: d.update(decision="MAYBE"))
    mut("EXECUTED receipt without effector_response", "receipt", rc,
        lambda d: d.update(type="ACTION_EXECUTED", effect="send"))
    mut("action receipt without payload_hash", "receipt", rc,
        lambda d: (d.update(type="ACTION_PROPOSED"), d.pop("payload_hash"), d.pop("approval_id")))
    mut("receipt with unknown event type", "receipt", rc, lambda d: d.update(type="ACTION_DONE"))
    mut("receipt with bad date-time", "receipt", rc, lambda d: d.update(ts="yesterday"))
    mut("provenance resolving to nothing", "provenance", pv, lambda d: d.pop("approval_id"))
    mut("provenance with short evidence tag", "provenance", pv, lambda d: d.update(basis="INFER"))
    mut("item with machine verdict HOLD", "item", flip,
        lambda d: d["recommendation"].update(verdict="HOLD"))
    mut("item embedding unknown field", "item", flip, lambda d: d.update(receipts=[rc]))
    mut("item with no sources", "item", flip, lambda d: d.update(sources=[]))
    return cases


def run_contract_checks(root: pathlib.Path = CONTRACTS_DIR, drift_ref: str | None = None) -> ContractReport:
    pin = json.loads((root / "PIN.json").read_text())
    rep = ContractReport(pin_commit=pin["source_commit"])

    # 1. pin integrity
    bad = []
    for rel, want in pin["files"].items():
        p = root / rel
        got = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "missing"
        if got != want:
            bad.append(rel)
    extra = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts} \
        - set(pin["files"]) - {"PIN.json"}
    rep.checks.append(CheckResult("pin integrity (byte-exact vs PIN.json)", not bad and not extra,
                                  f"modified={bad} unpinned={sorted(extra)}" if bad or extra else f"{len(pin['files'])} files"))

    # 2. optional drift check vs coordinator branch
    if drift_ref:
        drift = []
        for rel, want in pin["files"].items():
            try:
                blob = subprocess.run(["git", "show", f"{drift_ref}:{pin['source_path']}{rel}"],
                                      capture_output=True, check=True).stdout
                if "sha256:" + hashlib.sha256(blob).hexdigest() != want:
                    drift.append(rel)
            except subprocess.CalledProcessError:
                drift.append(rel + " (absent)")
        rep.checks.append(CheckResult(f"no drift vs {drift_ref}", not drift,
                                      f"drifted={drift}" if drift else "identical"))

    c = Contracts(root)
    rep.checks.append(CheckResult("all schemas are valid JSON Schema 2020-12", True, f"{len(c.schemas)} schemas"))

    # 3. positive examples
    for ex in sorted((root / "examples").glob("*.json")):
        kind = next(v for k, v in EXAMPLE_PREFIX.items() if ex.name.startswith(k))
        errs = c.errors(kind, json.loads(ex.read_text()))
        rep.checks.append(CheckResult(f"example validates: {ex.name}", not errs, "; ".join(errs[:3])))

    # 4. negative invariants
    for name, kind, doc in negative_cases(root):
        rejected = bool(c.errors(kind, doc))
        rep.checks.append(CheckResult(f"rejects: {name}", rejected, "" if rejected else "ACCEPTED an invalid document"))
    return rep


def contract_gap_probes(root: pathlib.Path = CONTRACTS_DIR) -> list[tuple[str, str, dict, str]]:
    """Documents the ADR/integration prose says are invalid but the frozen schema ACCEPTS.

    These are reported as findings for Agent 01 (contract owner). They are NOT counted as
    passes; the QA harness enforces each rule at runtime instead (see `enforced_by`).
    """
    ap = _example(root, "approval-hold.example.json")
    rc = _example(root, "receipt-approval-decided.example.json")
    probes = []

    def mut(name, kind, base, fn, enforced_by):
        d = copy.deepcopy(base)
        fn(d)
        probes.append((name, kind, d, enforced_by))

    mut("MODIFY with empty modifications (integration §4 says new_action_request_id is required)",
        "approval", ap, lambda d: (d.update(decision="MODIFY", modifications={}), d.pop("hold")),
        "mocks.workflow.Workflow.decide")
    mut("HOLD with empty hold block (no hold_until / wake_on)", "approval", ap,
        lambda d: d.update(hold={}), "mocks.workflow.Workflow.decide")
    mut("money approval without auth_context.step_up=true (ADR-0005 / approval.schema description)",
        "approval", ap, lambda d: (d.update(decision="YES"), d.pop("hold"), d["auth_context"].update(step_up=False)),
        "mocks.gateway.Gateway (grant check)")
    mut("ACTION_EXECUTED with effector_response.dry_run=false in MVP (A7)", "receipt", rc,
        lambda d: d.update(type="ACTION_EXECUTED", effect="send",
                           effector_response={"provider": "x", "status": "sent", "dry_run": False}),
        "mocks.gateway.Gateway check 8 + A7 audit query")
    mut("receipt prev_hash not a sha256 ref", "receipt", rc, lambda d: d.update(prev_hash="garbage"),
        "mocks.store.verify_chain")
    return probes


def run_gap_probes(root: pathlib.Path = CONTRACTS_DIR) -> list[CheckResult]:
    c = Contracts(root)
    out = []
    for name, kind, doc, enforced_by in contract_gap_probes(root):
        accepted = not c.errors(kind, doc)
        out.append(CheckResult(name, not accepted,
                               f"schema ACCEPTS — runtime-enforced in {enforced_by}" if accepted else "schema rejects"))
    return out
