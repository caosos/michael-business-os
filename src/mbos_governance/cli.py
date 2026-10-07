"""Host-local operator CLI: `mbos-gov` (Postgres, lane D schema).

  mbos-gov panic status
  mbos-gov panic freeze  --level L3|L2|L1 [--target X] --actor A --reason "..."     (role gateway)
  mbos-gov panic release --level L3|L2|L1 [--target X] --actor michael --reason "..." (role approver)
  mbos-gov policy check                          (file, or the running DB policy with MBOS_POLICY_SOURCE=db)
  mbos-gov policy publish --actor michael        (E-06: file -> lane D mbos.policy, receipted; role policy_admin)
  mbos-gov ledger verify
  mbos-gov render egress|litellm [--out FILE]   (generators; stdout if no --out; no network)
  mbos-gov freeze-requests apply FILE.jsonl     (B-04: apply lane B's side-channel freeze requests)
  mbos-gov reconcile [--older-than SECONDS]      (E-05: stuck claims; provider lookup, never re-send)
  mbos-gov alerts [--since-hours 24] [--ntfy]    (E-09: read-only alert queries; exit 2 on any CRITICAL; sends nothing)

Connection: --dsn, or env MBOS_GOV_DSN (one login for every role), or per role
MBOS_GOV_DSN_GATEWAY / _APPROVER / _AGENT_WRITE / _POLICY_ADMIN. --policy / MBOS_POLICY for the policy file.
A fresh database is FROZEN (lane D bootstrap); Michael releases it with `panic release --level L3`.
freeze/release re-render MBOS_EGRESS_FILE (var/egress_policy.json) and MBOS_LITELLM_FILE (var/litellm_keys.json).
Exit codes: 0 ok, 1 refused/invalid, 2 frozen or unreadable (status).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .gateway import ActionGateway, GatewayRefused
from .hooks import EgressPolicyHook, LiteLLMBudgetHook, _atomic_write, render_egress, render_litellm_keys
from .policy import PolicyStore, PolicyUnavailable
from .store_pg import ROLES, PgGovernanceStore, PgPanicStore


def dsns(arg: str | None) -> dict[str, str]:
    base = arg or os.environ.get("MBOS_GOV_DSN", "")
    out = {r: os.environ.get(f"MBOS_GOV_DSN_{r.upper()}", base) for r in ROLES}
    if not all(out.values()):
        raise SystemExit("mbos-gov: set --dsn or MBOS_GOV_DSN (or MBOS_GOV_DSN_<ROLE> for every role)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mbos-gov")
    ap.add_argument("--dsn")
    ap.add_argument("--policy")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("panic")
    p.add_argument("action", choices=["status", "freeze", "release"])
    p.add_argument("--level", choices=["L1", "L2", "L3"], default="L3")
    p.add_argument("--target")
    p.add_argument("--actor", default=os.environ.get("USER", "unknown"))
    p.add_argument("--reason", default="")
    pp = sub.add_parser("policy")
    pp.add_argument("action", choices=["check", "publish"])
    pp.add_argument("--actor", default=os.environ.get("USER", "unknown"))
    sub.add_parser("ledger").add_argument("action", choices=["verify"])
    r = sub.add_parser("render")
    r.add_argument("what", choices=["egress", "litellm"])
    r.add_argument("--out")
    fr = sub.add_parser("freeze-requests")
    fr.add_argument("action", choices=["apply"])
    fr.add_argument("file")
    al = sub.add_parser("alerts")
    al.add_argument("--since-hours", type=float, default=24.0)
    al.add_argument("--ntfy", action="store_true")
    rc = sub.add_parser("reconcile")
    rc.add_argument("--older-than", type=int)
    a = ap.parse_args(argv)
    policy_path = a.policy or os.environ.get("MBOS_POLICY", "policy/policy.v1.json")

    db_policy = os.environ.get("MBOS_POLICY_SOURCE", "file") == "db"
    if a.cmd == "policy" and a.action == "publish":
        from .policy_pg import publish
        try:
            out = publish(dsns(a.dsn)["policy_admin"], policy_path, Path(policy_path).with_name("content_rules.v1.json"), a.actor)
        except Exception as exc:  # noqa: BLE001
            print(f"refused: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(out, indent=2))
        return 0
    if a.cmd == "policy":
        try:
            if db_policy:
                from .policy_pg import PgPolicyStore
                pol = PgPolicyStore(dsns(a.dsn)["gateway"]).current()
            else:
                pol = PolicyStore(policy_path).current()
        except PolicyUnavailable as exc:
            print(f"POLICY UNREADABLE — gateway will deny everything: {exc}", file=sys.stderr)
            return 1
        print(f"policy ok: {pol.version} mode={pol.data['system_mode']} delegation={pol.data['delegation_enabled']}")
        return 0

    if a.cmd == "alerts":
        from datetime import datetime, timedelta, timezone
        from .alerts import collect, to_ntfy
        dsn = os.environ.get("MBOS_GOV_DSN_READER") or dsns(a.dsn)["gateway"]
        ttl = 300
        try:
            ttl = PolicyStore(policy_path).current().data["execution"]["claim_ttl_seconds"]
        except PolicyUnavailable:
            pass
        found = collect(dsn, datetime.now(timezone.utc) - timedelta(hours=a.since_hours), ttl)
        print(json.dumps(to_ntfy(found) if a.ntfy else found, indent=2, default=str))
        return 2 if any(x["severity"] == "critical" for x in found) else 0
    roles = dsns(a.dsn)
    panic = PgPanicStore(roles["gateway"])
    if a.cmd == "panic" and a.action == "status":
        st = panic.read()
        print(json.dumps({"global": st.global_state, "readable": st.readable, "error": st.error,
                          "frozen_agents": sorted(st.frozen_agents), "frozen_capabilities": sorted(st.frozen_capabilities),
                          "revision": st.revision}, indent=2))
        return 2 if st.globally_frozen else 0
    if a.cmd == "render":
        try:
            if db_policy:
                from .policy_pg import PgPolicyStore
                data = PgPolicyStore(roles["gateway"]).current().data
            else:
                data = PolicyStore(policy_path).current().data
        except PolicyUnavailable:
            data = None  # renders the frozen form
        doc = (render_egress if a.what == "egress" else render_litellm_keys)(data, panic.read())
        if a.out:
            _atomic_write(Path(a.out), doc)
        else:
            print(json.dumps(doc, indent=2, sort_keys=True))
        return 0

    store = PgGovernanceStore(roles)
    if a.cmd == "ledger":
        ok, msg = store.verify_chain()
        print(msg)
        return 0 if ok else 1
    if db_policy:
        from .policy_pg import PgPolicyStore
        ps = PgPolicyStore(roles["gateway"])
    else:
        ps = PolicyStore(policy_path)
    hooks = [EgressPolicyHook(os.environ.get("MBOS_EGRESS_FILE", "var/egress_policy.json"), ps),
             LiteLLMBudgetHook(os.environ.get("MBOS_LITELLM_FILE", "var/litellm_keys.json"), ps)]
    gw = ActionGateway(store, ps, panic, panic_hooks=hooks)
    if a.cmd == "freeze-requests":
        from .freeze_requests import apply_side_channel
        outs = apply_side_channel(gw, a.file)
        print(json.dumps([o.__dict__ for o in outs], indent=2))
        return 0 if all(o.applied or o.reasons == ["ALREADY_FROZEN"] for o in outs) else 1
    if a.cmd == "reconcile":
        outs = gw.reconcile(a.older_than)
        print(json.dumps([{"action_request_id": o.action_request_id, "outcome": o.outcome, "reasons": o.reasons}
                          for o in outs], indent=2))
        return 1 if any(r.startswith("NEEDS_HUMAN") for o in outs for r in o.reasons) else 0
    try:
        if a.action == "freeze":
            out = gw.engage_panic(a.level, a.target, a.actor, a.reason or "cli freeze")
        else:
            out = gw.release_panic(a.level, a.target, a.actor, a.reason)
    except (GatewayRefused, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - e.g. the database refused the role
        print(f"refused by database: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"revision": out["state"]["revision"], "global": out["state"]["global"]["state"],
                      "cancelled": out.get("cancelled", []), "hooks": out.get("hooks", {}),
                      **({"error": out["error"]} if out.get("error") else {})}, indent=2))
    return 1 if out.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
