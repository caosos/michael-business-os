"""F-141: real-Chrome evidence for owner-entered finds on /market. Isolated staging: stub store, committed test GSA fixture, SYNTHETIC finds in a scratch
MBOS_MARKET_FINDS_FILE, loopback ephemeral port, DRY-RUN. Chrome's outgoing requests are logged and must all be to 127.0.0.1.
usage: .venv/bin/python tools/f141_finds_shots.py OUTDIR"""
import json, os, subprocess, sys, tempfile, threading, shutil
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ.update(MBOS_MARKET_PREFS_FILE=str(tmp / "prefs.json"), MBOS_MARKET_FINDS_FILE=str(tmp / "market_finds.json"), MBOS_DECISION_CASES_DIR=str(tmp / "cases"))
from tests.test_market_f47 import FIX, ASOF  # noqa: E402
shutil.copy(FIX, tmp / "gsa.json"); (tmp / "gsa.asof").write_text(ASOF.isoformat()); os.environ["MBOS_GSA_CACHE"] = str(tmp / "gsa.json")
from operator_ui import market_finds as mf  # noqa: E402
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
app = App(StubStore(), operator_pin="123456", campaigns_file=str(tmp / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"
PATH = "/market?go=1&base=Conway+AR&broad=1&radius=150&max_price=100000"
reqs, log = [], []
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    def page(w, h):
        pg = br.new_page(viewport={"width": w, "height": h}); pg.on("request", lambda r: reqs.append(r.url)); return pg
    pg = page(1648, 1000); pg.goto(base + PATH); pg.wait_for_load_state()
    def open_add():
        if not pg.evaluate("()=>document.querySelector('#add-find').open"):
            pg.locator("#add-find summary").click()
    open_add()
    def add(link, title, price, loc, cond, src):
        pg.locator("#add-find input[name=link]").fill(link); pg.locator("#add-find input[name=title]").fill(title); pg.locator("#add-find input[name=price]").fill(price)
        pg.locator("#add-find input[name=location]").fill(loc); pg.locator("#add-find select[name=condition]").select_option(cond); pg.locator("#add-find select[name=source]").select_option(src)
        pg.locator("#add-find button.mk-add").click(); pg.wait_for_load_state(); open_add()
    add("https://www.facebook.com/marketplace/item/111/", "SYNTHETIC utility trailer 5x8", "450", "Conway, AR", "used", "facebook")
    add("https://littlerock.craigslist.org/syn/222.html", "SYNTHETIC flatbed trailer", "900", "Little Rock, AR", "used", "craigslist")
    add("https://offerup.com/item/detail/333", "SYNTHETIC equipment generator", "", "Nowhereville, ZZ", "", "offerup")
    open_add()
    pg.locator("#add-find input[name=title]").fill("SYNTHETIC dup"); pg.locator("#add-find input[name=link]").fill("https://www.facebook.com/marketplace/item/111/?utm=x")
    pg.locator("#add-find input[name=location]").fill("Conway, AR"); pg.locator("#add-find button.mk-add").click(); pg.wait_for_load_state()
    dup_msg = pg.locator(".flash").first.inner_text() if pg.locator(".flash").count() else ""
    pg.goto(base + PATH); pg.locator("#your-finds").scroll_into_view_if_needed(); pg.screenshot(path=str(out / "1648x1000-your-finds.png"))
    gsa_n = pg.evaluate("()=>document.querySelector('.mk-main h2').innerText")
    pg.goto(base + PATH + "&max_price=300"); pg.locator("#your-finds").scroll_into_view_if_needed(); pg.screenshot(path=str(out / "1648x1000-max-price-300.png"))
    pg.goto(base + PATH); pg.locator("#your-finds [data-find] .mk-x").first.click(); pg.wait_for_load_state()
    pg.locator("#hidden-list summary").click(); pg.screenshot(path=str(out / "1648x1000-after-hide.png"))
    pg.locator("#hidden-list button", has_text="Undo hide").first.click(); pg.wait_for_load_state()
    first = pg.locator("#your-finds [data-find]").first; first.locator("summary", has_text="Edit").click(); first.locator("button", has_text="Delete").click(); pg.wait_for_load_state()
    pg.locator("#deleted-finds summary").click(); pg.locator("#deleted-finds").scroll_into_view_if_needed(); pg.screenshot(path=str(out / "1648x1000-after-delete.png"))
    pg.locator("#deleted-finds button").first.click(); pg.wait_for_load_state()
    m = page(390, 844); m.goto(base + PATH); m.locator("#your-finds").scroll_into_view_if_needed(); m.screenshot(path=str(out / "390x844-your-finds.png"))
    n_after_restore = pg.locator("#your-finds [data-find]").count()
    br.close()
files = json.loads((tmp / "market_finds.json").read_text())["finds"]
iso = {"finds_file": "scratch tmp (MBOS_MARKET_FINDS_FILE)", "inside_repo": str(ROOT) in str(tmp / "market_finds.json"), "n_finds": len(files), "chrome_requests_all_loopback": all(u.startswith(base) or u.startswith("data:") for u in reqs),
       "external_requests": sorted({u for u in reqs if not (u.startswith(base) or u.startswith("data:"))}), "duplicate_message": dup_msg, "gsa_heading_with_finds": gsa_n, "finds_after_delete_undo": n_after_restore,
       "network": "none: loopback only; links entered are text, never requested", "code_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
       "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": "SYNTHETIC finds only"}
(out / "evidence.json").write_text(json.dumps(iso, indent=1)); print(json.dumps(iso, indent=1))
