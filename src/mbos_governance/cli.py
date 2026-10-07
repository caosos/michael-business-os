"""Host-local operator CLI: `mbos-gov`.

  mbos-gov panic status
  mbos-gov panic init   --actor michael --reason "..."      (creates state FROZEN)
  mbos-gov panic freeze  --level L3|L2|L1 [--target X] --actor A --reason "..."
  mbos-gov panic release --level L3|L2|L1 [--target X] --actor michael --reason "..."
  mbos-gov policy check
  mbos-gov ledger verify

Paths: --db / --policy / --panic, or env MBOS_GOV_DB, MBOS_POLICY, MBOS_PANIC_STATE.
`freeze` works even if the database cannot be opened (state file first, receipt best-effort).
Exit codes: 0 ok, 1 refused/invalid, 2 frozen (status) — scripts can test `panic status`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .gateway import ActionGateway, GatewayRefused
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
    gw = ActionGateway(store, PolicyStore(policy_path), panic)
    try:
        if a.action == "freeze":
            out = gw.engage_panic(a.level, a.target, a.actor, a.reason or "cli freeze")
        else:
            out = gw.release_panic(a.level, a.target, a.actor, a.reason)
    except (GatewayRefused, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"revision": out["state"]["revision"], "global": out["state"]["global"]["state"],
                      "cancelled": out.get("cancelled", [])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
