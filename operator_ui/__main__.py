"""python -m operator_ui serve [--port N]

Talks to the spine's database (MBOS_DATABASE_URL / MBOS_SYSTEM_DATABASE_URL, as for `mbos`).
A worker (`mbos worker`) must be running to act on decisions. The UI never executes anything.
Step-up PIN for irreversible/money YES comes from MBOS_OPERATOR_PIN (unset = refuse).
"""

import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="operator_ui")
    ap.add_argument("cmd", choices=["serve"])
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)

    from mbos.db.engine import app_engine

    from .backend import SpineBackend
    from .server import App, serve

    pin = os.environ.get("MBOS_OPERATOR_PIN") or None
    if not pin:
        print("note: MBOS_OPERATOR_PIN unset — YES on irreversible/money requests will be refused (fail-closed)")
    serve(App(SpineBackend(app_engine()), operator_pin=pin), port=a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
