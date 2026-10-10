"""F-52: real-browser run of /market (gallery, strict filters, validation, preference learning). Stub store, real GSA cache, DRY-RUN.
usage: .venv/bin/python tools/f52_browser.py OUTDIR"""
import json, os, sys, tempfile, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["MBOS_MARKET_PREFS_FILE"] = str(Path(tempfile.mkdtemp()) / "prefs.json")
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
app = App(StubStore(), operator_pin="123456", campaigns_file=str(Path(tempfile.mkdtemp()) / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"
log = {}
cards = "()=>[...document.querySelectorAll('.mk-row .mk-g')].map(x=>x.querySelector('.ti').innerText)"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.goto(base + "/market?go=1"); pg.screenshot(path=str(out / "01-gallery-default.png"), full_page=True)
    log["default_rows"] = pg.evaluate("()=>[...document.querySelectorAll('.mk-row')].map(r=>r.dataset.row+':'+r.querySelectorAll('.mk-g').length)")
    log["default_cards"] = pg.evaluate(cards)
    log["card_button_style"] = pg.evaluate("()=>{const s=getComputedStyle(document.querySelector('.mk-g .mk-pref button'));return {bg:s.backgroundColor,color:s.color,opacity:s.opacity}}")
    log["sidebar_inputs"] = pg.evaluate("()=>[...document.querySelectorAll('.mk-side [form=mkform]')].map(i=>i.name)")
    log["unchecked_open"] = pg.evaluate("()=>{const d=document.querySelector('#unchecked-section');return d?d.open:null}")
    pg.fill("#min_price", "900"); pg.fill("#max_price", "100"); pg.click("button.mk-go"); pg.wait_for_load_state()
    log["invalid_msg"] = pg.inner_text("#filter-errors") if pg.query_selector("#filter-errors") else None
    log["invalid_cards"] = len(pg.evaluate(cards)); pg.screenshot(path=str(out / "02-invalid-max-price.png"))
    pg.goto(base + "/market?go=1&broad=1&radius=150&max_price=100000&keywords=")
    log["strict_cards"] = len(pg.evaluate(cards)); log["strict_unchecked"] = pg.evaluate("()=>document.querySelectorAll('#unchecked-section .mk-g').length")
    pg.screenshot(path=str(out / "03-strict-150mi-100000.png"), full_page=True)
    pg.goto(base + "/market?go=1&row1=electronics&row2=trailers&row3=&row4=&broad=1&keywords=trailer")
    log["custom_rows"] = pg.evaluate("()=>[...document.querySelectorAll('.mk-row')].map(r=>r.dataset.row+':'+r.querySelectorAll('.mk-g').length)")
    log["empty_row_text"] = "No matching known inventory" in pg.content(); pg.screenshot(path=str(out / "04-custom-rows-empty-electronics.png"), full_page=True)
    pg.goto(base + "/market?go=1&broad=1&radius=150&keywords=&view=list&sort=title")
    first = pg.evaluate("()=>document.querySelector('.mk-main .mk-pref [name=title]').value")
    pg.click(".mk-main .mk-pref button[value=more]"); pg.wait_for_load_state()
    pg.click(".mk-main .mk-pref button[value=save]"); pg.wait_for_load_state()
    log["after_feedback_why"] = pg.evaluate("()=>[...document.querySelectorAll('[data-why]')].map(x=>x.innerText).slice(0,3)")
    log["prefs_panel"] = pg.inner_text("#prefs"); pg.screenshot(path=str(out / "05-preferences.png"), full_page=True)
    pg.click("#prefs button[value=reset]"); pg.wait_for_load_state(); log["after_reset"] = pg.inner_text("#prefs")
    pg.set_viewport_size({"width": 390, "height": 800}); pg.goto(base + "/market?go=1"); pg.screenshot(path=str(out / "06-mobile.png"))
    log["mobile_overflow"] = pg.evaluate("()=>document.documentElement.scrollWidth>document.documentElement.clientWidth")
    log["first_title"] = first
(out / "run-log.json").write_text(json.dumps(log, indent=1)); print(json.dumps(log, indent=1))
