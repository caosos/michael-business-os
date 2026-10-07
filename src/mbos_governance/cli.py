"""Host-local operator CLI: `mbos-gov`.

  mbos-gov panic status
  mbos-gov panic init   --actor michael --reason "..."      (creates state FROZEN)
  mbos-gov panic freeze  --level L3|L2|L1 [--target X] --actor A --reason "..."
  mbos-gov panic release --level L3|L2|L1 [--target X] --actor michael --reason "..."
  mbos-gov policy check
  mbos-gov ledger verify
  mbos-gov render egress|litellm [--out FILE]   (generators; stdout if no --out; no network)

Paths: --db / --policy / --panic, or env MBOS_GOV_DB, MBOS_POLICY, MBOS_PANIC_STATE.
freeze/release also re-render MBOS_EGRESS_FILE (var/egress_policy.json) and MBOS_LITELLM_FILE
(var/litellm_keys.json). The DBOS cancel hook is wired by the DBOS runtime (Agent 01), not here.
`freeze` works even if the database cannot be opened (state file first, receipt best-effort).
Exit codes: 0 ok, 1 refused/invalid, 2 frozen (status) — scripts can test `panic status`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .gateway import ActionGateway, GatewayRefused
from .hooks import EgressPolicyHook, LiteLLMBudgetHook, render_egress, render_litellm_keys
from .panic import PanicStore
from .policy import PolicyStore, PolicyUnavailable
from .store import GovernanceStore


def _paths(a):
    return (a.db or os.environ.get("MBOS_GOV_DB", "var/governance.sqlite3"),
            a.policy or os.environ.get("MBOS_POLICY", "policy/policy.v1.json"),
            a.panic or os.environ.get("MBOS_PANIC_STATE", "var/panic_state.json"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mbos-gov")
    ap.add_argument("--db")
    ap.add_argument("--policy")
    ap.add_argument("--panic")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("panic")
    p.add_argument("action", choices=["status", "init", "freeze", "release"])
    p.add_argument("--level", choices=["L1", "L2", "L3"], default="L3")
    p.add_argument("--target")
    p.add_argument("--actor", default=os.environ.get("USER", "unknown"))
    p.add_argument("--reason", default="")
    sub.add_parser("policy").add_argument("action", choices=["check"])
    sub.add_parser("ledger").add_argument("action", choices=["verify"])
    r = sub.add_parser("render")
    r.add_argument("what", choices=["egress", "litellm"])
    r.add_argument("--out")
    a = ap.parse_args(argv)
    db, policy_path, panic_path = _paths(a)
    panic = PanicStore(panic_path)

    if a.cmd == "panic" and a.action == "status":
        st = panic.read()
        print(json.dumps({"global": st.global_state, "readable": st.readable, "error": st.error,
                          "frozen_agents": sorted(st.frozen_agents), "frozen_capabilities": sorted(st.frozen_capabilities),
                          "revision": st.revision}, indent=2))
        return 2 if st.globally_frozen else 0
    if a.cmd == "panic" and a.action == "init":
        try:
            panic.init(a.actor, a.reason or "initialized FROZEN")
        except FileExistsError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"initialized {panic_path} (FROZEN). Release with: mbos-gov panic release --level L3 --actor michael --reason ...")
        return 0
    if a.cmd == "render":
        try:
            data = PolicyStore(policy_path).current().data
        except PolicyUnavailable:
            data = None  # renders the frozen form
        doc = (render_egress if a.what == "egress" else render_litellm_keys)(data, panic.read())
        text = json.dumps(doc, indent=2, sort_keys=True)
        if a.out:
            from .hooks import _atomic_write
            _atomic_write(Path(a.out), doc)
        else:
            print(text)
        return 0
    if a.cmd == "policy":
        try:
            pol = PolicyStore(policy_path).current()
        except PolicyUnavailable as exc:
            print(f"POLICY UNREADABLE — gateway will deny everything: {exc}", file=sys.stderr)
            return 1
        print(f"policy ok: {pol.version} mode={pol.data['system_mode']} delegation={pol.data['delegation_enabled']}")
        return 0

    try:
        store = GovernanceStore(db)
    except Exception as exc:  # noqa: BLE001
        if a.cmd == "panic" and a.action == "freeze":
            panic.mutate(a.level, a.target, True, a.actor, a.reason or "cli freeze")
            print(f"FROZEN ({a.level} {a.target or 'global'}) — database unavailable ({exc}); receipt NOT written, "
                  f"record it once the ledger is back.", file=sys.stderr)
            with open(str(panic.path) + ".journal.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event": "KILL_SWITCH_CHANGED", "level": a.level, "target": a.target,
                                     "actor": a.actor, "reason": a.reason, "receipt_error": str(exc)}) + "\n")
            return 0
        print(f"cannot open governance store: {exc}", file=sys.stderr)
        return 1
    if a.cmd == "ledger":
        ok, msg = store.verify_chain()
        print(msg)
        return 0 if ok else 1
    ps = PolicyStore(policy_path)
    hooks = [EgressPolicyHook(os.environ.get("MBOS_EGRESS_FILE", "var/egress_policy.json"), ps),
             LiteLLMBudgetHook(os.environ.get("MBOS_LITELLM_FILE", "var/litellm_keys.json"), ps)]
    gw = ActionGateway(store, ps, panic, panic_hooks=hooks)
    try:
        if a.action == "freeze":
            out = gw.engage_panic(a.level, a.target, a.actor, a.reason or "cli freeze")
        else:
            out = gw.release_panic(a.level, a.target, a.actor, a.reason)
    except (GatewayRefused, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"revision": out["state"]["revision"], "global": out["state"]["global"]["state"],
                      "cancelled": out.get("cancelled", []), "hooks": out.get("hooks", {})}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
