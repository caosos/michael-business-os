"""python -m operator_ui {serve|tick|verify} [--db PATH] [--seed] [--port N]

Step-up PIN for irreversible/money YES comes from MBOS_OPERATOR_PIN (unset = refuse).
"""

import argparse
import os
import sys

from .approvals import ApprovalService
from .effectors import DryRunEffector
from .gateway import DryRunGateway
from .seed import seed
from .server import App, serve
from .store import Store
from .util import Clock


def build(db):
    clock = Clock()
    store = Store(db)
    svc = ApprovalService(store, clock, operator_pin=os.environ.get("MBOS_OPERATOR_PIN") or None)
    svc.gateway = DryRunGateway(store, clock, DryRunEffector(store), svc)
    return store, svc, clock


def main(argv=None):
    ap = argparse.ArgumentParser(prog="operator_ui")
    ap.add_argument("cmd", choices=["serve", "tick", "verify"])
    ap.add_argument("--db", default=os.environ.get("MBOS_UI_DB", "operator_ui.sqlite3"))
    ap.add_argument("--seed", action="store_true", help="load ILLUSTRATIVE demo opportunities if empty")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    store, svc, clock = build(a.db)
    if a.seed and seed(store, clock.now()):
        print("seeded 3 ILLUSTRATIVE opportunities")
    if a.cmd == "verify":
        ok, bad, n = store.verify_chain()
        print(f"verify_chain: {'OK' if ok else f'BROKEN at seq {bad}'} ({n} receipts)")
        return 0 if ok else 1
    if a.cmd == "tick":
        for ev in svc.tick():
            print(*ev)
        return 0
    for r in svc.gateway.resume():  # finish anything interrupted mid-execution (A5)
        print("resumed:", r)
    if not svc.operator_pin:
        print("note: MBOS_OPERATOR_PIN unset — YES on irreversible/money requests will be refused (fail-closed)")
    serve(App(store, svc, clock), port=a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
