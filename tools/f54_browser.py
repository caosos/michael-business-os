"""F-54: real-Chrome staging run on an isolated instance (stub store, cached GSA fixture/real cache, DRY-RUN, no external navigation).
Cases A16 keyboard, A17 saved search, B01 1648x1000, B12 link source, B16 back-nav, B18 HTML escape, B19 raw ID comparison, C07 copy, F-54 prefs.
usage: .venv/bin/python tools/f54_browser.py OUTDIR"""
import json, os, re, shutil, sys, tempfile, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["MBOS_MARKET_PREFS_FILE"] = str(tmp / "prefs.json")
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
raw = json.loads((ROOT / "tests/fixtures/gsa_live/active-auctions.json").read_text())
hostile = "<script>window.__x=1</script><img src=x onerror=window.__x=1>&amp;"
raw["Results"][0]["itemName"] = "Trailer " + hostile                       # B18 injection fixture
cache = tmp / "gsa.json"; cache.write_text(json.dumps(raw)); cache.with_suffix(".asof").write_text("2026-10-10T00:19:00+00:00")
os.environ["MBOS_GSA_CACHE"] = str(cache)


def serve():
    app = App(StubStore(), operator_pin="123456", campaigns_file=str(tmp / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


log = {}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1648, "height": 1000})
    h1, base = serve()
    pg.goto(base + "/market?go=1&broad=1&radius=25000&keywords=")
    cols = "()=>{const t=[...document.querySelectorAll('.mk-row')][0];const g=[...t.querySelectorAll('.mk-g')];return {row:t.dataset.row,cards:g.length,tops:[...new Set(g.map(c=>Math.round(c.getBoundingClientRect().top)))].length,w:Math.round(g[0].getBoundingClientRect().width)}}"
    log["B01_1648x1000"] = {"first_card": pg.evaluate("()=>{const r=document.querySelector('.mk-g').getBoundingClientRect();return {top:Math.round(r.top+scrollY),vh:innerHeight}}"),
                            "overflow": pg.evaluate("()=>document.documentElement.scrollWidth>document.documentElement.clientWidth"),
                            "max_columns_in_a_row": pg.evaluate("()=>Math.max(...[...document.querySelectorAll('.mk-gal')].map(g=>{const c=[...g.querySelectorAll('.mk-g')];return c.length?c.filter(x=>Math.abs(x.getBoundingClientRect().top-c[0].getBoundingClientRect().top)<2).length:0}))"),
                            "card_width": pg.evaluate("()=>Math.round(document.querySelector('.mk-g').getBoundingClientRect().width)")}
    pg.screenshot(path=str(out / "B01-1648x1000.png"))
    # B18 escaping
    log["B18_script_executed"] = pg.evaluate("()=>window.__x===1")
    log["B18_script_elements_from_title"] = pg.evaluate("()=>document.querySelectorAll('.mk-main script, .mk-main img[onerror]').length")
    log["B18_title_text_shown_literally"] = "<script>window.__x=1</script>" in pg.inner_text(".mk-main")
    # A16 keyboard: Tab to min slider, move with keys, submit with Enter, read chips
    pg.goto(base + "/market?go=1&new=1")
    pg.focus("#min_r"); pg.keyboard.press("ArrowRight"); pg.keyboard.press("ArrowRight")
    log["A16_slider_value_after_keys"] = pg.evaluate("()=>document.querySelector('#min_r').value")
    pg.focus("#max_price"); pg.fill("#max_price", "19000"); pg.keyboard.press("Enter"); pg.wait_for_load_state()
    log["A16_chips_after_keyboard_submit"] = pg.inner_text("#applied-filters"); log["A16_errors"] = bool(pg.query_selector("#filter-errors"))
    pg.focus("#min_price"); pg.keyboard.press("Tab")
    log["A16_tab_moves_focus_visibly"] = pg.evaluate("()=>document.activeElement.tagName+':'+(document.activeElement.name||document.activeElement.id)")
    pg.screenshot(path=str(out / "A16-keyboard.png"))
    # B16 back navigation
    pg.goto(base + "/market?go=1&broad=1&max_price=100&radius=150")
    n1, c1 = pg.evaluate("()=>document.querySelectorAll('.mk-g').length"), pg.inner_text("#applied-filters")
    pg.goto(base + "/market?go=1&broad=1&max_price=100000&radius=25000")
    n2, c2 = pg.evaluate("()=>document.querySelectorAll('.mk-g').length"), pg.inner_text("#applied-filters")
    pg.go_back(); pg.wait_for_load_state()
    n3, c3 = pg.evaluate("()=>document.querySelectorAll('.mk-g').length"), pg.inner_text("#applied-filters")
    pg.go_forward(); pg.wait_for_load_state()
    n4, c4 = pg.evaluate("()=>document.querySelectorAll('.mk-g').length"), pg.inner_text("#applied-filters")
    log["B16_back_forward"] = {"first": [n1, c1], "second": [n2, c2], "back_equals_first": (n3, c3) == (n1, c1), "forward_equals_second": (n4, c4) == (n2, c2)}
    # F-54 prefs: valid, invalid, plain load, new instance
    pg.goto(base + "/market?go=1&radius=120&max_price=500")
    pg.goto(base + "/market?go=1&radius=x"); log["F54_invalid_shows_error"] = bool(pg.query_selector("#filter-errors"))
    pg.goto(base + "/market"); log["F54_plain_load_after_invalid"] = {"error_banner": bool(pg.query_selector("#filter-errors")), "chips": pg.inner_text("#applied-filters")}
    h1.shutdown(); h1.server_close(); h2, base2 = serve()
    pg.goto(base2 + "/market"); log["F54_new_instance_plain_load"] = {"error_banner": bool(pg.query_selector("#filter-errors")), "chips": pg.inner_text("#applied-filters")}
    pg.screenshot(path=str(out / "F54-restored-after-invalid.png"))
    # A17 saved search keeps strict limits (min, max, radius, category)
    pg.goto(base2 + "/market?go=1&new=1&keywords=trailer&min_price=10&max_price=500&radius=120&cat=trailers")
    pg.click("#save-search summary"); pg.fill("#save-search input[name=pin]", "123456") if pg.query_selector("#save-search input[name=pin]") else None
    pg.click("#save-search button[name=do]"); pg.wait_for_load_state()
    log["A17_after_save_url"] = pg.url.split("?")[0] + "?" + pg.url.split("?", 1)[-1][:60]
    link = pg.query_selector("a[href*='run=']")
    if link:
        pg.goto(link.get_attribute("href") if link.get_attribute("href").startswith("http") else base2 + link.get_attribute("href"))
    log["A17_saved_run_chips"] = pg.inner_text("#applied-filters"); log["A17_errors"] = bool(pg.query_selector("#filter-errors"))
    pg.screenshot(path=str(out / "A17-saved-search-run.png"))
    # B12 / B19: DOM vs raw source, no external navigation
    pg.goto(base2 + "/market?go=1&broad=1&radius=25000&keywords=")
    dom = pg.evaluate("()=>[...document.querySelectorAll('.mk-g')].map(c=>({lot:c.dataset.lot,hrefs:[...c.querySelectorAll('a[href]')].map(a=>a.href)}))")
    src = {f"{r['saleNo']}-{r['lotNo']}": r["itemDescURL"] for r in raw["Results"]}
    log["B19_dom_lots"] = sorted({d["lot"] for d in dom}); log["B19_raw_ids"] = sorted(src)
    log["B12_all_links_are_source_urls"] = all(h in set(src.values()) or h.startswith(base2) for d in dom for h in d["hrefs"])
    log["B12_external_hosts"] = sorted({re.sub(r"^https?://([^/]+).*", r"\1", h) for d in dom for h in d["hrefs"] if not h.startswith(base2)})
    # C07: no economic claims in the page copy
    txt = pg.inner_text("body").lower()
    log["C07_forbidden_phrases_present"] = [w for w in ("profit", "resale value", "you will make", "guaranteed", "buy now", "worth $") if w in txt]
    log["C07_has_research_needed"] = "research needed" in txt
    b.close()
(out / "run-log.json").write_text(json.dumps(log, indent=1)); print(json.dumps(log, indent=1))
