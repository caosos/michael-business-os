"""F-143: real-Chrome evidence for the radius slider + numeric price fields + no hidden origin. Isolated staging (stub store, COPY of the real GSA cache, loopback port, DRY-RUN).
usage: .venv/bin/python tools/f143_live_check.py OUTDIR  -> screenshots + f143-evidence.json; exit 1 if any check fails."""
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
KNOWN = "()=>[...document.querySelectorAll('.mk-g')].filter(c=>!c.closest('#unchecked-section')).map(c=>c.dataset.lot)"
LAST = "()=>{const b=document.querySelector('button.mk-go').getBoundingClientRect();return [...document.querySelectorAll('#mkfilters input,#mkfilters select')].filter(i=>i.type!=='hidden'&&i.getBoundingClientRect().height>0&&!i.closest('.st-list')&&!i.closest('details:not([open])')).every(i=>i.getBoundingClientRect().bottom<=b.top+1)}"
log, fails = [], []


def check(name, ok, **kw):
    log.append({"check": name, "ok": bool(ok), **kw})
    if not ok:
        fails.append(name)


with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    for vname, w, h in (("desktop-1648x1000", 1648, 1000), ("mobile-390x844", 390, 844)):
        pg = br.new_page(viewport={"width": w, "height": h}); sc = lambda n: pg.screenshot(path=str(out / f"{vname}-{n}.png"), full_page=True)  # noqa: E731
        pg.goto(base + "/market?new=1")                                         # NEW USER: nothing remembered
        pg.goto(base + "/market")
        check(f"{vname}: new user has empty origin and no Conway text", pg.input_value("input[name=base]") == "" and "Conway" not in pg.content(), origin=pg.input_value("input[name=base]"))
        sc("new-user")
        pg.goto(base + "/market?go=1&broad=1&base=Conway+AR&radius=150")
        check(f"{vname}: price sliders absent", pg.evaluate("()=>!document.getElementById('min_r')&&!document.getElementById('max_r')&&!document.querySelector('[name=min_r],[name=max_r],[name=prev_min],[name=prev_max]')"))
        check(f"{vname}: Search Now last after every filter", pg.evaluate(LAST))
        check(f"{vname}: radius slider visible with min/max labels", pg.is_visible("#radius_r") and pg.inner_text("#radius-min") == "0 miles" and pg.inner_text("#radius-max") == "500 miles")
        for how, val in (("slider", "0"), ("slider", "60"), ("slider", "120"), ("slider", "500"), ("typed", "97.9"), ("typed", "750"), ("typed", "25000"), ("typed", "0")):
            if how == "slider":
                pg.eval_on_selector("#radius_r", "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}))}", val)
            else:
                pg.fill("#radius", val)
            shown = pg.inner_text("#radius-out")
            pg.click("button.mk-go"); pg.wait_for_load_state()
            ids = pg.evaluate(KNOWN)
            check(f"{vname}: {how} {val}: displayed miles == submitted", shown == f"{float(val):g} miles" and f"radius={val}" in pg.url and pg.input_value("#radius") == val, shown=shown, url=pg.url, known_count=len(ids), ids=ids)
            sc(f"radius-{how}-{val}")
        pg.goto(base + "/market?go=1&broad=1&base=Conway+AR&radius=150&max_price=100000")
        wide = pg.evaluate(KNOWN)
        pg.fill("#max_price", "25"); pg.click("button.mk-go"); pg.wait_for_load_state()
        low = pg.evaluate(KNOWN)
        check(f"{vname}: typed max price changes results", len(low) < len(wide) and set(low) <= set(wide), before=len(wide), after=len(low))
        pg.fill("#min_price", "5"); pg.focus("#min_price")
        with pg.expect_navigation():
            pg.keyboard.press("Enter")
        check(f"{vname}: Enter submits typed min price", "min_price=5" in pg.url and "max_price=25" in pg.url)
        pg.goto(base + "/market?go=1&broad=1&base=72032&radius=100&max_r=5&min_r=900&prev_max=20000")
        check(f"{vname}: obsolete slider fields ignored", pg.input_value("#max_price") == "" and pg.input_value("#min_price") == "")
        r1 = pg.evaluate(KNOWN)
        pg.goto(base + "/market?go=1&broad=1&base=Fayetteville+AR&radius=100")
        r2 = pg.evaluate(KNOWN)
        check(f"{vname}: second supported origin gives its own located result set", r1 != r2 and pg.input_value("input[name=base]") == "Fayetteville AR", conway_zip_ids=len(r1), fayetteville_ids=len(r2), differs=r1 != r2)
        sc("second-origin")
        pg.goto(base + "/market?go=1&broad=1&base=Conway+AR&radius=87&min_price=3&max_price=900"); pg.goto(base + "/market"); pg.reload()
        check(f"{vname}: origin/radius/price persist across reload", (pg.input_value("input[name=base]"), pg.input_value("#radius"), pg.input_value("#min_price"), pg.input_value("#max_price")) == ("Conway AR", "87", "3", "900"))
        pg.goto(base + "/market?go=1&broad=1&base=Conway+AR&loc_mode=state&state=AR&radius=10")
        check(f"{vname}: By State does not apply the radius", "the radius is NOT applied" in pg.inner_text("#location-scope"), scope=pg.inner_text("#location-scope")[:120])
        pg.close()
    br.close()
meta = {"code_sha": code["sha"], "operator_ui_tests_tools_dirty": code["dirty"], "cache_sha256": real_sha, "cache_as_of_utc": asof, "store": "STUB (no database)", "port": httpd.server_address[1],
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "failed": fails, "checks": log}
(out / "f143-evidence.json").write_text(json.dumps(meta, indent=1))
print(json.dumps({"checks": len(log), "failed": fails, "dirty": code["dirty"], "sha": code["sha"]}))
sys.exit(1 if fails else 0)
