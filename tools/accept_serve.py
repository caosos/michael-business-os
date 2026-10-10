"""Isolated /market server for the persistence acceptance run: REAL operator_ui code from an exported commit, REAL cached GSA file, but a STUB store
(no database) with its own PIN and its own campaigns + prefs files. Real persistence layers (campaigns file, prefs file) survive a process restart; the
decision-queue database is NOT involved. Usage: accept_serve.py EXPORT_DIR STATE_DIR PORT   (run with a Python that has the lane 06 dependencies)"""
import os, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path

export, state, port = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
sys.path.insert(0, str(export))
state.mkdir(parents=True, exist_ok=True)
os.environ["MBOS_MARKET_PREFS_FILE"] = str(state / "prefs.json")
os.environ["MBOS_GSA_CACHE"] = os.environ.get("MBOS_GSA_CACHE", str(Path.home() / "business-os-worktrees/agent-01-coordinator/var/cache/gsa-active-auctions.json"))
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402

app = App(StubStore(), operator_pin="123456", campaigns_file=str(state / "campaigns.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
print("serving", port, flush=True)
httpd.serve_forever()
