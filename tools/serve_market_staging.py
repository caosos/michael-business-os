"""F-57: isolated staging server for tools/capture_market.py (loopback, scratch prefs, stub store, DRY-RUN; the GSA cache is read from MBOS_GSA_CACHE or the default).
usage: .venv/bin/python tools/serve_market_staging.py PORT"""
import os, sys, tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["MBOS_MARKET_PREFS_FILE"] = str(tmp / "prefs.json")
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402

app = App(StubStore(), operator_pin="123456", campaigns_file=str(tmp / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), make_handler(app)).serve_forever()
