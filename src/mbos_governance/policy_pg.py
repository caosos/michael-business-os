"""E-06: PDP policy data in lane D's `mbos.policy` / `policy_current` (versioned, append-only, receipted).

Rows published (role policy_admin, via mbos.publish_policy => CONFIG_VERSION_BUMPED receipt each):
  governance:policy/1          limits.document = the full validated policy document (what the PDP reads)
  governance:content_rules/1   limits.document = the E-04 content rules
  category:<name>              decision / tier / limits {max_tier, budget_bucket, require_cost_estimate, quiet_hours}
  capability:<name>            category / decision / limits {effector}
The per-key rows make lane D's own constraints apply (e.g. policy_money_gated: money is never `allow`) and
let reporting read the matrix; the PDP reads the document row and REQUIRES the per-key rows to agree.

READ (PgPolicyStore.current) — fail closed: no row, DB error, a document failing the schema PINNED IN CODE
(schemas/policy.schema.json), a cross-check failure, or a per-key row disagreeing with the document =>
PolicyUnavailable, and the gateway denies everything.

The JSON file under policy/ stays the reviewed source in git; `publish` is the receipted act that makes it
the running policy. Publishing is idempotent: unchanged keys are not re-versioned.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import __version__
from .content_guard import ContentRules, ContentRulesUnavailable, rules_from_data
from .ids import canonical_json, sha256_tagged
from .policy import Policy, PolicyUnavailable, load_policy, packaged_schema, policy_from_data

DOC_KEY = "governance:policy/1"
RULES_KEY = "governance:content_rules/1"


def _rows(policy: Policy, rules_doc: dict) -> dict[str, dict]:
    d = policy.data
    rows = {
        DOC_KEY: {"decision": "deny", "limits": {"document": d, "version": policy.version},
                  "reason": f"governance policy {policy.version} (document; PDP source)"},
        RULES_KEY: {"decision": "deny", "limits": {"document": rules_doc},
                    "reason": f"content rules {rules_doc.get('version')} (E-04)"},
    }
    for cat, spec in d["categories"].items():
        rows[f"category:{cat}"] = {"category": cat, "tier": spec["tier"], "decision": spec["decision"],
                                   "limits": {k: spec[k] for k in ("max_tier", "budget_bucket", "require_cost_estimate",
                                                                   "quiet_hours")},
                                   "reason": f"{cat}: {spec['decision']} tier {spec['tier']} ({policy.version})"}
    for cap, spec in d["capabilities"].items():
        cat = d["categories"][spec["category"]]
        rows[f"capability:{cap}"] = {"capability": cap, "category": spec["category"], "tier": cat["tier"],
                                     "decision": cat["decision"], "limits": {"effector": spec["effector"]},
                                     "reason": f"{cap} -> {spec['category']} via {spec['effector']} ({policy.version})"}
    return rows


def _comparable(row: dict) -> dict:
    return {k: row.get(k) for k in ("category", "capability", "tier", "decision", "limits")}


def publish(dsn_policy_admin: str, policy_path: str | Path, rules_path: str | Path, actor: str) -> dict[str, Any]:
    """Validate the files exactly like the PDP will (pinned schema), then publish changed keys in ONE transaction."""
    policy_path, rules_path = Path(policy_path), Path(rules_path)
    pol = load_policy(policy_path, schema_path=None)
    pol = policy_from_data(pol.data, packaged_schema(), str(policy_path))   # the pinned schema must accept it too
    rules_doc = json.loads(rules_path.read_text("utf-8"))
    rules_from_data(rules_doc)                                              # compiles, or raises
    wanted = _rows(pol, rules_doc)
    published, unchanged = [], []
    with psycopg.connect(dsn_policy_admin, row_factory=dict_row) as conn, conn.transaction():
        current = {r["policy_key"]: r for r in conn.execute(
            "SELECT policy_key, version, category, capability, tier, decision, limits FROM mbos.policy_current")}
        inputs = [{"ref": str(p), "hash": "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()}
                  for p in (policy_path, rules_path)]
        prov = conn.execute("SELECT mbos.record_provenance(%s) AS id", (Jsonb({
            "actor_type": "human" if actor == "michael" else "system", "basis": "FACT",
            "tool_name": "mbos_governance.policy_pg.publish", "tool_version": __version__,
            "config_version": pol.version, "inputs_used": inputs,
            **({"human_actor": actor} if actor == "michael" else {})}),)).fetchone()["id"]
        for key, row in sorted(wanted.items()):
            cur = current.get(key)
            if cur is not None and _comparable(cur) == _comparable(row):
                unchanged.append(key)
                continue
            nxt = (cur["version"] + 1) if cur else 1
            digest = sha256_tagged(canonical_json(_comparable(row))).split(":", 1)[1][:16]
            conn.execute("SELECT mbos.publish_policy(%s, %s, %s, %s)", (
                Jsonb({"policy_key": key, "version": nxt, **{k: v for k, v in row.items() if v is not None},
                       "created_by": actor, "provenance_ids": [prov]}),
                Jsonb({"type": "human" if actor == "michael" else "system", "id": actor}),
                f"publish {key} v{nxt}", f"policy:{key}:v{nxt}:{digest}"))
            published.append(key)
    return {"policy_version": pol.version, "published": published, "unchanged": unchanged}


class PgPolicyStore:
    """PDP policy from lane D. Same interface as PolicyStore (`current()`), plus `content_rules_store()`."""

    path = None  # no file

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._local = threading.local()
        self._schema = packaged_schema()
        self._cache: tuple[str, Policy] | None = None
        self._lock = threading.Lock()

    def _conn(self) -> psycopg.Connection:
        c = getattr(self._local, "conn", None)
        if c is None or c.closed or c.broken:
            c = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row, connect_timeout=5)
            self._local.conn = c
        return c

    def _current_rows(self) -> dict[str, dict]:
        try:
            return {r["policy_key"]: r for r in self._conn().execute(
                "SELECT policy_id, policy_key, version, category, capability, tier, decision, limits FROM mbos.policy_current")}
        except Exception as exc:  # noqa: BLE001
            self._local.conn = None
            raise PolicyUnavailable(f"policy_current unreadable: {type(exc).__name__}: {exc}") from exc

    def current(self) -> Policy:
        rows = self._current_rows()
        doc = rows.get(DOC_KEY)
        if doc is None:
            raise PolicyUnavailable(f"no {DOC_KEY} row in mbos.policy_current (publish first): default deny")
        stamp = doc["policy_id"] + "|" + ",".join(sorted(r["policy_id"] for r in rows.values()))
        with self._lock:
            if self._cache and self._cache[0] == stamp:
                return self._cache[1]
        pol = policy_from_data((doc["limits"] or {}).get("document"), self._schema, f"postgres:{DOC_KEY}@v{doc['version']}")
        if (doc["limits"] or {}).get("version") != pol.version:
            raise PolicyUnavailable("policy document hash does not match its recorded version (tampered?)")
        want = _rows(pol, {})
        drift = [k for k, w in want.items() if k not in (DOC_KEY, RULES_KEY)
                 and (k not in rows or _comparable(rows[k]) != _comparable(w))]
        if drift:
            raise PolicyUnavailable(f"per-key policy rows disagree with the document: {drift[:5]}")
        with self._lock:
            self._cache = (stamp, pol)
        return pol

    def content_rules_store(self) -> "PgContentRulesStore":
        return PgContentRulesStore(self)


class PgContentRulesStore:
    def __init__(self, policies: PgPolicyStore):
        self.policies = policies

    def current(self) -> ContentRules:
        try:
            rows = self.policies._current_rows()
        except PolicyUnavailable as exc:
            raise ContentRulesUnavailable(str(exc)) from exc
        row = rows.get(RULES_KEY)
        if row is None:
            raise ContentRulesUnavailable(f"no {RULES_KEY} row in mbos.policy_current")
        return rules_from_data((row["limits"] or {}).get("document"))
