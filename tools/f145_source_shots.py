"""F-145: real-Chrome evidence for the /market source seam. Isolated staging (stub store, COPY of the real GSA cache, scrubbed .eml fixtures from tests/fixtures/alerts, loopback, DRY-RUN, no IMAP, no network).
usage: .venv/bin/python tools/f145_source_shots.py OUTDIR -> screenshots + f145-evidence.json; exit 1 if any check fails."""
import hashlib, json, os, shutil, subprocess, sys, tempfile, threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["MBOS_MARKET_PREFS_FILE"] = str(tmp / "prefs.json")
REAL = Path(os.environ.get("F55_REAL_CACHE", "/home/michaelos/business-os-worktrees/agent-01-coordinator/var/cache/gsa-active-auctions.json"))
real_sha, asof = hashlib.sha256(REAL.read_bytes()).hexdigest(), REAL.with_suffix(".asof").read_text().strip()
shutil.copy(REAL, tmp / "gsa.json"); shutil.copy(REAL.with_suffix(".asof"), tmp / "gsa.asof")
os.environ["MBOS_GSA_CACHE"] = str(tmp / "gsa.json")
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731
code = {"sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", "operator_ui", "tests", "tools"))}
app = App(StubStore(), operator_pin="123456", campaigns_file=str(tmp / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"
FIX = str(ROOT / "tests" / "fixtures" / "alerts")
LAST = "()=>{const b=document.querySelector('button.mk-go').getBoundingClientRect();return [...document.querySelectorAll('#mkfilters input,#mkfilters select')].filter(i=>i.type!=='hidden'&&i.getBoundingClientRect().height>0&&!i.closest('.st-list')&&!i.closest('details:not([open])')).every(i=>i.getBoundingClientRect().bottom<=b.top+1)}"
Q = "/market?go=1&broad=1&base=Conway+AR&radius=150"
log, fails = [], []


def check(name, ok, **kw):
    log.append({"check": name, "ok": bool(ok), **kw})
    if not ok:
        fails.append(name)


def staging(on):
    for k, v in (("MBOS_STAGING_FIXTURES", "1"), ("MBOS_MARKET_FIXTURE_MAIL_DIR", FIX)):
        os.environ.pop(k, None)
        if on:
            os.environ[k] = v


with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    for vname, w, h in (("desktop-1648x1000", 1648, 1000), ("mobile-390x844", 390, 844)):
        pg = br.new_page(viewport={"width": w, "height": h}); sc = lambda n: pg.screenshot(path=str(out / f"{vname}-{n}.png"), full_page=True)  # noqa: E731
        staging(False)
        pg.goto(base + Q + "&source=gsa")
        check(f"{vname}: GSA default shows GSA lots and no fixture label", pg.locator(".mk-g").count() > 0 and "FIXTURE" not in pg.content(), lots=pg.locator(".mk-g").count())
        sc("gsa-unchanged")
        pg.goto(base + Q + "&source=govdeals")
        check(f"{vname}: no staging flag -> GovDeals NOT CONNECTED, no listings", "govdeals: not connected" in pg.inner_text("#results-top").lower() and pg.locator(".mk-g").count() == 0 and "FIXTURE" not in pg.content())
        sc("govdeals-not-connected-no-flag")
        staging(True)
        pg.goto(base + Q + "&source=govdeals")
        txt = pg.inner_text("#results-top")
        check(f"{vname}: staging GovDeals shows FIXTURE banner and per-row not-live status", pg.is_visible("#fixture-banner") and "FIXTURE / not live" in pg.inner_text("#fixture-banner") and "GovDeals: FIXTURE / not live" in txt)
        li = pg.inner_text("li[data-src='GovDeals']")
        check(f"{vname}: fixture row never says connected", "connected" not in li.lower(), row=li)
        check(f"{vname}: Craigslist/eBay/Facebook rows NOT CONNECTED", all(f"{n}: NOT CONNECTED" in txt for n in ("Craigslist", "eBay", "Facebook Marketplace")))
        cards = pg.locator(".mk-g"); n = cards.count()
        check(f"{vname}: fixture cards carry label, source link, price, town, freshness", n >= 1 and all(t in pg.inner_text(".mk-g") for t in ("FIXTURE / not live", "GovDeals", "fetched 2026-10-07", "Conway, AR", "$350")) and pg.locator(".mk-g a[href^='https://www.govdeals.com/']").count() >= 1, cards=n)
        sc("govdeals-fixture-gallery")
        pg.goto(base + Q + "&source=govdeals&view=list&min_price=100&max_price=400")
        check(f"{vname}: price filter applies to fixture records", "Utility Trailer 5x10" in pg.inner_text("#results-top") and "<h2>1 result" in pg.content())
        pg.goto(base + Q + "&source=govdeals&max_price=300")
        check(f"{vname}: max price 300 hides the $350 fixture trailer", "Utility Trailer 5x10" not in pg.inner_text("#results-top") and "0 results" in pg.inner_text("#results-top"))
        sc("govdeals-fixture-price-filter")
        pg.goto(base + Q + "&source=all")
        names = pg.evaluate("()=>[...document.querySelectorAll('.mk-g')].map(c=>c.innerText)")
        check(f"{vname}: all merges GSA with labelled fixture cards", any("FIXTURE / not live" in t for t in names) and any("FIXTURE" not in t for t in names), cards=len(names))
        sc("all-merged")
        pg.goto(base + "/market?go=1&broad=1&base=Conway+AR&radius=150&source=ebay")
        check(f"{vname}: eBay stays not connected even on staging", "ebay: not connected" in pg.inner_text("#results-top").lower() and pg.locator(".mk-g").count() == 0)
        check(f"{vname}: Search Now still last after the filters", pg.evaluate(LAST))
        pg.close()
    br.close()
meta = {"code_sha": code["sha"], "operator_ui_tests_tools_dirty": code["dirty"], "cache_sha256": real_sha, "cache_as_of_utc": asof, "store": "STUB (no database)", "fixture_dir": "tests/fixtures/alerts (scrubbed)",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "failed": fails, "checks": log}
(out / "f145-evidence.json").write_text(json.dumps(meta, indent=1))
print(json.dumps({"checks": len(log), "failed": fails, "dirty": code["dirty"], "sha": code["sha"]}))
sys.exit(1 if fails else 0)
