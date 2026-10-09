"""LEARN (research §16; C-07): calibrate from Outcome v1 records and PROPOSE a config bump.

Nothing here writes, applies or activates anything. The flow is:

1. ``load_outcomes(conn)`` reads Outcome v1 documents (and item metadata) from Agent 04's
   read views (``mbos.v_outcome_documents``, ``mbos.v_item_documents``) through any DB-API
   connection with the read role, or callers pass Outcome v1 dicts directly.
2. ``calibrate(outcomes, item_meta)`` gives Brier scores for probability forecasts and MAPE/bias
   for continuous estimates, per field and per group.
3. ``propose_learn_bump(...)`` turns calibration into deterministic prior updates (shrinkage, so a
   handful of outcomes moves a prior only a little) and builds the next document plus a **tier-0
   ActionRequest draft** (capability ``config.scoring.bump``). Its payload carries the ENTIRE
   proposed document, so Michael approves exact content.
4. Only after Michael's YES does the State lane (04) archive the current file, write the new one
   and emit ``CONFIG_VERSION_BUMPED``. Historical scorecards keep replaying under their version.

Contract gaps (requested under ADR-0009): frozen ActionRequest v1.0.0 requires ``item_id`` and
has no ``config`` category. A config change is not item-scoped, so the draft omits ``item_id``,
uses the proposed category ``config_change`` and lists both under ``contract_gaps``
on the proposal (the frozen ActionRequest forbids extra properties, so the draft itself carries only
contract fields; evidence refs live inside the hashed payload).
"""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from decimal import Decimal
from typing import Any, Iterable

from . import __version__ as LEARN_VERSION
from .canonical import content_hash, derived_ulid, parse_ts
from .config import ScoringConfig, dump_config
from .numeric import D, ZERO, fine

TOOL_NAME = "mbos_economics.learn"
CAPABILITY = "config.scoring.bump"

_PROB_FIELDS = {"rehab.repair_success_prob", "resale.sale_prob", "job.win_prob", "job.completion_prob"}


# --------------------------------------------------------------------------- metrics

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


def bias(pairs: list[tuple[float, float]]) -> Decimal:
    """Mean of actual/predicted - 1: positive means estimates run LOW."""
    return fine(sum((D(a) / D(p) for p, a in pairs), ZERO) / D(len(pairs)) - 1)


def shrink_toward_base_rate(prior: float, successes: int, n: int, prior_weight: int = 10) -> Decimal:
    """Beta-binomial style shrink: posterior = (k*prior + successes) / (k + n)."""
    if n < 0 or not 0 <= successes <= n:
        raise ValueError("invalid counts")
    return fine((D(prior_weight) * D(prior) + D(successes)) / (D(prior_weight) + D(n)))


# --------------------------------------------------------------------------- inputs

def item_meta_from_docs(item_docs: Iterable[dict], priors: ScoringConfig | None = None) -> dict[str, dict]:
    """item_id -> {type, category, condition, source}; only structured fields. ``category`` is the PRIOR group
    (F-117: an ``other_asset`` TV is ``consumer_electronics``, whose priors are non-zero and can calibrate)."""
    from .estimate import load_priors, prior_category
    priors = priors or load_priors()
    meta = {}
    for d in item_docs:
        n = d.get("normalized") or {}
        meta[d["item_id"]] = {"type": d.get("type"), "category": prior_category(d, priors) or d.get("category"),
                              "condition": n.get("condition") if n.get("condition") in ("new", "used", "parts") else "unknown",
                              "source": (d.get("sources") or [{}])[0].get("source")}
    return meta


def load_outcomes(conn) -> tuple[list[dict], dict[str, dict]]:
    """Read Outcome v1 documents + item metadata from Agent 04's read views (read role, read-only).

    ``conn`` is any DB-API 2 connection (psycopg 3 works). The query is SELECT-only.
    """
    cur = conn.cursor()
    cur.execute("SELECT doc FROM mbos.v_outcome_documents ORDER BY doc->>'observed_at', doc->>'outcome_id'")
    outcomes = [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in cur.fetchall()]
    ids = sorted({o["item_id"] for o in outcomes})
    docs: list[dict] = []
    if ids:
        cur.execute("SELECT doc FROM mbos.v_item_documents WHERE item_id = ANY(%s)", (ids,))
        docs = [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in cur.fetchall()]
    return outcomes, item_meta_from_docs(docs)


# --------------------------------------------------------------------------- calibration

def _group(field: str, meta: dict) -> str:
    if field == "job.win_prob":
        return f"source={meta.get('source')}"
    if field.startswith("job."):
        return f"service/{meta.get('category')}"
    return f"flip/{meta.get('category')}/{meta.get('condition')}"


def calibrate(outcomes: list[dict], item_meta: dict[str, dict]) -> dict:
    """Per field and group: n, pairs and Brier (probabilities) or MAPE + bias (continuous)."""
    pairs: dict[str, dict[str, list]] = {}
    used: list[str] = []
    for o in sorted(outcomes, key=lambda o: (o["observed_at"], o["outcome_id"])):
        meta = item_meta.get(o["item_id"])
        if meta is None:
            continue
        used.append(o["outcome_id"])
        for pv in o.get("predicted_vs_actual") or []:
            f, p, a = pv.get("field"), pv.get("predicted"), pv.get("actual")
            if f is None or p is None or a is None:
                continue
            if f in _PROB_FIELDS and a not in (0, 1, True, False):
                continue
            if f not in _PROB_FIELDS and (D(p) == 0 or D(a) == 0):
                continue
            pairs.setdefault(f, {}).setdefault(_group(f, meta), []).append((p, int(a) if f in _PROB_FIELDS else a))
    fields = {}
    for f, groups in sorted(pairs.items()):
        all_pairs = [x for g in groups.values() for x in g]
        if f in _PROB_FIELDS:
            fields[f] = {"kind": "probability", "n": len(all_pairs), "brier": brier(all_pairs),
                         "groups": {g: {"n": len(v), "brier": brier(v), "successes": sum(a for _, a in v),
                                        "mean_predicted": fine(sum((D(p) for p, _ in v), ZERO) / D(len(v)))}
                                    for g, v in sorted(groups.items())}}
        else:
            fields[f] = {"kind": "continuous", "n": len(all_pairs), "mape": mape(all_pairs), "bias": bias(all_pairs),
                         "groups": {g: {"n": len(v), "mape": mape(v), "bias": bias(v)} for g, v in sorted(groups.items())}}
    return {"outcomes_used": used, "fields": fields}


# --------------------------------------------------------------------------- proposals

def _bump(version: str) -> str:
    year, month, patch = version.split(".")
    return f"{year}.{month}.{int(patch) + 1}"


def _get(doc: dict, path: str):
    node = doc
    for p in path.split("."):
        node = node[p]
    return node["value"] if isinstance(node, dict) and "value" in node else node


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


def _json_native(raw: dict) -> dict:
    return json.loads(dump_config(raw))


def _action_request(target: str, from_v: str, to_v: str, new_doc: dict, diff: list, rationale: str,
                    evidence_refs: list[str], provenance_id: str, as_of: str) -> dict:
    payload = {"target": target, "from_version": from_v, "to_version": to_v, "diff": diff, "rationale": rationale,
               "evidence_refs": sorted(evidence_refs), "document": new_doc, "document_hash": content_hash(new_doc)}
    ph = content_hash(payload)
    return {
        "action_request_id": derived_ulid("areq", as_of, f"learn|{ph}"),
        "created_at": as_of,
        "proposed_by": "agent-03-economics",
        "on_behalf_of": "michael",
        "capability": CAPABILITY,
        "category": "config_change",
        "payload": payload,
        "payload_hash": ph,
        "idempotency_key": f"config.bump:{target}:{from_v}->{to_v}:{ph[7:23]}",
        "reversibility": "reversible",
        "untrusted_inputs_present": True,
        "tier": 0,
        "status": "drafted",
        "expires_at": (parse_ts(as_of) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provenance_ids": [provenance_id],
    }


CONTRACT_GAPS = [
    "item_id omitted: a config change is not item-scoped (ADR-0009 request: optional item_id for system actions)",
    "category 'config_change' is not in the v1.0.0 enum (ADR-0009 request)",
]


def _bump_document(raw: dict, version_key: str, changes: dict[str, object], rationale: str) -> tuple[dict, list]:
    new = copy.deepcopy(raw)
    diff = []
    for path, value in sorted(changes.items()):
        v = D(value) if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) else value
        before = _set(new, path, v)
        diff.append({"path": path, "from": json.loads(dump_config({"x": before}))["x"],
                     "to": json.loads(dump_config({"x": v}))["x"]})
    new_version = _bump(raw[version_key])
    new[version_key] = new_version
    new["supersedes"] = raw[version_key]
    new["_changelog"] = list(new.get("_changelog", [])) + [f"{new_version}: {rationale}"]
    return new, diff


def propose_config_bump(cfg: ScoringConfig, changes: dict[str, object], rationale: str,
                        evidence_refs: list[str], proposed_at: str, *, target: str = "scoring-config",
                        version_key: str = "scoring_config_version") -> dict:
    """Generic proposal for explicit changes. Writes nothing."""
    if not changes:
        raise ValueError("a bump needs at least one change")
    if not evidence_refs:
        raise ValueError("a bump needs provenance (outcome / calibration ids)")
    new, diff = _bump_document(cfg.raw, version_key, changes, rationale)
    prov_id = derived_ulid("prov", proposed_at, "learn|" + content_hash({"diff": diff, "refs": sorted(evidence_refs)}))
    areq = _action_request(target, cfg.version, new[version_key], _json_native(new), diff, rationale,
                           evidence_refs, prov_id, proposed_at)
    return {"from_version": cfg.version, "to_version": new[version_key], "diff": diff, "config": new,
            "payload_hash": areq["payload_hash"], "action_request": areq, "action_request_draft": areq,
            "contract_gaps": CONTRACT_GAPS}


def propose_learn_bump(outcomes: list[dict], item_meta: dict[str, dict], priors: ScoringConfig, as_of: str) -> dict:
    """Calibrate, derive prior updates by rule, and PROPOSE an estimation-priors bump. Writes nothing.

    Rules (parameters in priors ``learn``; all REC):
      * repair_success_prob[cat][cond], sale_prob[cat], win_prob_by_source[src]: beta-binomial shrink of
        the CURRENT prior toward observed successes, weight ``prior_weight``.
      * labor_hours[cat][cond]: multiply by the shrunk mean actual/predicted ratio.
      * Only groups with n >= ``min_outcomes_per_group`` and |relative change| >= ``min_relative_change``.
    """
    report = calibrate(outcomes, item_meta)
    k = int(priors.num("learn.prior_weight"))
    min_n = int(priors.num("learn.min_outcomes_per_group"))
    min_rel = priors.num("learn.min_relative_change")
    changes: dict[str, Decimal] = {}
    notes: list[str] = []

    def consider(path: str, new: Decimal, why: str) -> None:
        old = D(_get(priors.raw, path))
        if old != 0 and abs(new - old) / old >= min_rel:
            changes[path] = new
            notes.append(f"{path}: {old} -> {new} ({why})")

    for f, info in report["fields"].items():
        for g, s in info["groups"].items():
            if s["n"] < min_n:
                continue
            parts = g.split("/")
            if f == "rehab.repair_success_prob" and parts[0] == "flip" and parts[2] in ("new", "used", "parts", "unknown"):
                path = f"flip.{parts[1]}.repair_success_prob.{parts[2]}"
                old = D(_get(priors.raw, path))
                consider(path, shrink_toward_base_rate(old, s["successes"], s["n"], k), f"{s['successes']}/{s['n']} repaired")
            elif f == "resale.sale_prob" and parts[0] == "flip":
                path = f"flip.{parts[1]}.sale_prob"
                old = D(_get(priors.raw, path))
                consider(path, shrink_toward_base_rate(old, s["successes"], s["n"], k), f"{s['successes']}/{s['n']} sold")
            elif f == "rehab.labor_hours" and parts[0] == "flip" and parts[2] in ("new", "used", "parts", "unknown"):
                path = f"flip.{parts[1]}.labor_hours.{parts[2]}"
                old = D(_get(priors.raw, path))
                ratio = (D(k) + D(s["n"]) * (1 + s["bias"])) / (D(k) + D(s["n"]))
                consider(path, (old * ratio).quantize(Decimal("0.01")), f"actual/predicted bias {s['bias']} over n={s['n']}")
            elif f == "job.win_prob" and g.startswith("source="):
                src = g.split("=", 1)[1]
                path = f"service_general.win_prob_by_source.{src}"
                try:
                    old = D(_get(priors.raw, path))
                except KeyError:
                    continue
                consider(path, shrink_toward_base_rate(old, s["successes"], s["n"], k), f"{s['successes']}/{s['n']} won")

    outcome_prov = sorted({p for o in outcomes if o["outcome_id"] in report["outcomes_used"] for p in o["provenance_ids"]})
    report_hash = content_hash(json.loads(dump_config({"r": report}))["r"])
    prov_id = derived_ulid("prov", as_of, f"learn|{report_hash}|{priors.hash}")
    provenance = {
        "provenance_id": prov_id, "created_at": as_of, "actor_type": "system", "agent_name": "agent-03-economics",
        "basis": "INFERENCE", "tool_name": TOOL_NAME, "tool_version": LEARN_VERSION, "config_version": priors.version,
        "inputs_used": [{"ref": o["outcome_id"], "hash": content_hash(o)} for o in outcomes
                        if o["outcome_id"] in report["outcomes_used"]]
                       + [{"ref": f"estimation-priors@{priors.version}", "hash": priors.hash}],
        **({"derived_from": outcome_prov} if outcome_prov else {}),
    }
    out: dict[str, Any] = {"report": json.loads(dump_config({"r": report}))["r"], "provenance": provenance,
                           "changes": notes, "proposal": None}
    if changes:
        rationale = f"LEARN from {len(report['outcomes_used'])} outcomes: " + "; ".join(notes)
        new, diff = _bump_document(priors.raw, "priors_version", changes, rationale)
        areq = _action_request("estimation-priors", priors.version, new["priors_version"], _json_native(new), diff,
                               rationale, report["outcomes_used"], prov_id, as_of)
        out["proposal"] = {"from_version": priors.version, "to_version": new["priors_version"], "diff": diff,
                           "action_request": areq, "contract_gaps": CONTRACT_GAPS}
    return out


def verify_proposal(action_request: dict) -> bool:
    """For the gateway/UI: the payload hash and the embedded document hash both reproduce."""
    p = action_request["payload"]
    return (content_hash(p) == action_request["payload_hash"]
            and content_hash(p["document"]) == p["document_hash"])
