"""F-53: real-Chrome run of /market: first-viewport cards, restart persistence (two separate App instances sharing only the prefs file),
validation of slider + direct-query values, 390px layout. Stub store, real cached GSA file, DRY-RUN.
usage: .venv/bin/python tools/f53_browser.py OUTDIR"""
import json, os, sys, tempfile, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["MBOS_MARKET_PREFS_FILE"] = str(Path(tempfile.mkdtemp()) / "prefs.json")
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)


def serve():
    app = App(StubStore(), operator_pin="123456", campaigns_file=str(Path(tempfile.mkdtemp()) / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


log = {}
first_card = "()=>{const c=document.querySelector('.mk-g');if(!c)return null;const r=c.getBoundingClientRect();return {top:Math.round(r.top+scrollY),bottom:Math.round(r.bottom+scrollY),vh:innerHeight}}"
rows = "()=>[...document.querySelectorAll('.mk-row')].map(r=>r.dataset.row+':'+r.querySelectorAll('.mk-g').length)"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    h1, base = serve()
    pg.goto(base + "/market?go=1")
    log["desktop_first_card"] = pg.evaluate(first_card); log["desktop_rows"] = pg.evaluate(rows)
    log["desktop_cards_in_first_viewport"] = pg.evaluate("()=>[...document.querySelectorAll('.mk-g')].filter(c=>c.getBoundingClientRect().top<innerHeight-40).length")
    log["page_height"] = pg.evaluate("()=>document.documentElement.scrollHeight")
    pg.screenshot(path=str(out / "01-first-viewport-1280x800.png"))
    pg.screenshot(path=str(out / "01b-full-page.png"), full_page=True)
    # restart persistence: set choices on instance 1, read them on a brand-new instance 2
    pg.goto(base + "/market?go=1&broad=1&cat=trailers&cat=equipment&row1=equipment&row2=trailers&row3=&row4=&sort=bid&max_price=100000&radius=150")
    log["inst1_rows"] = pg.evaluate(rows)
    h1.shutdown(); h1.server_close()
    h2, base2 = serve()
    pg.goto(base2 + "/market")
    log["inst2_rows_after_restart"] = pg.evaluate(rows)
    log["inst2_chips"] = pg.inner_text("#applied-filters"); log["inst2_sort"] = pg.evaluate("()=>document.querySelector('select[name=sort]').value")
    log["inst2_checked_cats"] = pg.evaluate("()=>[...document.querySelectorAll('input[name=cat]:checked')].map(i=>i.value)")
    pg.screenshot(path=str(out / "02-after-restart-persisted.png"))
    pg.goto(base2 + "/market?new=1"); pg.goto(base2 + "/market"); log["after_new_chips"] = pg.inner_text("#applied-filters")
    # validation through the real controls: sliders (moved via keyboard) and direct query
    pg.goto(base2 + "/market?go=1&new=1"); pg.goto(base2 + "/market?go=1")
    pg.focus("#min_r"); pg.keyboard.press("End"); pg.fill("#max_price", "100"); pg.click("button.mk-go"); pg.wait_for_load_state()
    log["slider_min_over_typed_max_msg"] = pg.inner_text("#filter-errors") if pg.query_selector("#filter-errors") else None
    log["slider_inverted_cards"] = pg.evaluate("()=>document.querySelectorAll('.mk-g').length")
    pg.screenshot(path=str(out / "03-slider-inverted-refused.png"))
    pg.goto(base2 + "/market?go=1&min_r=-3&prev_min=1")
    log["slider_negative_msg"] = pg.inner_text("#filter-errors") if pg.query_selector("#filter-errors") else None
    pg.goto(base2 + "/market?go=1&broad=1&keywords=&min_price=100&max_price=100")
    log["equal_bounds_filter_errors"] = bool(pg.query_selector("#filter-errors"))
    log["equal_bounds_chips"] = pg.inner_text("#applied-filters"); pg.screenshot(path=str(out / "04-equal-bounds-allowed.png"))
    pg.goto(base2 + "/market?go=1&broad=1&radius=150&max_price=100000&keywords=")
    log["strict_checked"] = pg.evaluate("()=>[...document.querySelectorAll('.mk-row .mk-g')].length")
    log["strict_unchecked_in_closed_section"] = pg.evaluate("()=>{const d=document.querySelector('#unchecked-section');return {open:d.open,n:d.querySelectorAll('.mk-g').length}}")
    # mobile
    pg.set_viewport_size({"width": 390, "height": 800}); pg.goto(base2 + "/market?go=1")
    log["mobile_first_card"] = pg.evaluate(first_card)
    log["mobile_overflow"] = pg.evaluate("()=>document.documentElement.scrollWidth>document.documentElement.clientWidth")
    log["mobile_search_button_visible"] = pg.evaluate("()=>{const r=document.querySelector('button.mk-go').getBoundingClientRect();return r.width>0&&r.right<=innerWidth}")
    pg.screenshot(path=str(out / "05-mobile-390.png")); pg.screenshot(path=str(out / "05b-mobile-390-full.png"), full_page=True)
    b.close()
(out / "run-log.json").write_text(json.dumps(log, indent=1)); print(json.dumps(log, indent=1))
