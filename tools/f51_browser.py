"""F-51: real-browser harness. Serves the Operator UI (stub store, real GSA cache, DRY-RUN) and drives system Chrome via Playwright.
usage: .venv/bin/python tools/f51_browser.py OUTDIR [diagnose|run]"""
import json, os, sys, tempfile, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
mode = sys.argv[2] if len(sys.argv) > 2 else "run"
PIN = "123456"
app = App(StubStore(), operator_pin=PIN, campaigns_file=str(Path(tempfile.mkdtemp()) / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"
log = {}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.goto(base + "/market")
    def btn():
        return pg.evaluate("""()=>{const b=[...document.querySelectorAll('.mk-form button')].find(x=>x.textContent.trim()=='Search');
          const s=getComputedStyle(b);return {disabled:b.disabled,opacity:s.opacity,color:s.color,bg:s.backgroundColor,pe:s.pointerEvents,cursor:s.cursor,
          ratio:null,text:b.textContent.trim()}}""")
    log["search_button"] = btn()
    pg.screenshot(path=str(out / f"{mode}-search-button.png"), clip={"x": 230, "y": 60, "width": 1000, "height": 220})
    if mode == "run":
        exec(open(Path(__file__).with_name("f51_run_steps.py")).read())
    (out / f"{mode}-log.json").write_text(json.dumps(log, indent=1))
    b.close()
print(json.dumps(log, indent=1))
