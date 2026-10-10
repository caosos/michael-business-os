"""F-137: isolated staging (stub store, COPY of the real GSA cache, loopback, DRY-RUN, test PIN only). One real server PROCESS, then a REAL kill + new process.
(a) corrected-label shots (gallery + list), (b) state panel at scrollY=0 (scroll recorded), (c) REAL Chrome Save click for states/mode/also-radius, reopen, process restart.
usage: .venv/bin/python tools/f137_browser.py OUTDIR"""
import hashlib, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright  # noqa: E402

tmp = Path(tempfile.mkdtemp()); out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
REAL = Path(os.environ.get("F55_REAL_CACHE", "/home/michaelos/business-os-worktrees/agent-01-coordinator/var/cache/gsa-active-auctions.json"))
shutil.copy(REAL, tmp / "gsa.json"); shutil.copy(REAL.with_suffix(".asof"), tmp / "gsa.asof")
env = {**os.environ, "MBOS_STAGING_DIR": str(tmp), "MBOS_GSA_CACHE": str(tmp / "gsa.json")}
PIN = "123456"
git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731


def start():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    pr = subprocess.Popen([sys.executable, str(ROOT / "tools/serve_market_staging.py"), str(port)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/market", timeout=1); break
        except Exception: time.sleep(0.1)
    return pr, f"http://127.0.0.1:{port}"


VIS = "()=>[...document.querySelectorAll('.mk-g')].filter(c=>!c.closest('#unchecked-section')&&!c.closest('details')).map(c=>c.dataset.lot)"
STATE = "()=>({mode:document.querySelector('input[name=loc_mode]:checked').value,states:[...document.querySelectorAll('input[name=state]:checked')].map(i=>i.value).sort(),also:document.querySelector('input[name=also_radius]').checked})"
res = {"code_sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", "operator_ui", "tests", "tools")), "cache_sha256": hashlib.sha256(REAL.read_bytes()).hexdigest(),
       "cache_as_of": REAL.with_suffix(".asof").read_text().strip(), "store": "STUB", "pid_before": None, "pid_after": None, "shots": [], "persistence": {}}
pr, base = start(); res["pid_before"] = pr.pid
Q = "go=1&base=Conway+AR&broad=1&radius=150&loc_mode=state&state=AR&state=TX&also_radius=1&max_price=2000"
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    for vn, w, h in (("desktop-1648x1000", 1648, 1000), ("mobile-390x844", 390, 844)):
        for name, path in (("labels-gallery", "/market?go=1&base=Conway+AR&broad=1&radius=150&view=gallery"), ("labels-list", "/market?go=1&base=Conway+AR&broad=1&radius=150&max_price=500&view=list"),
                           ("state-AR-TX", "/market?go=1&base=Conway+AR&broad=1&radius=150&max_price=500&loc_mode=state&state=AR&state=TX")):
            pg = br.new_page(viewport={"width": w, "height": h}); pg.goto(base + path); pg.wait_for_load_state()
            sel = ".gal-lbl" if name == "labels-gallery" else "#auction-labels"
            txt = pg.locator(sel).first.inner_text() if name != "state-AR-TX" else None
            m = {"file": f"{vn}-{name}.png", "scrollY": pg.evaluate("scrollY"), "label_text": txt, "search_now_in_first_viewport": pg.evaluate("()=>{const b=document.querySelector('button.mk-go').getBoundingClientRect();return b.top>=0&&b.bottom<=innerHeight}")}
            if name != "state-AR-TX":     # labels are below the fold: scroll the first label into view, and say so
                pg.evaluate(f"()=>document.querySelector('{sel}').scrollIntoView({{block:'center'}})"); m["kind"] = "SCROLLED viewport (first label centred)"; m["scrollY_after"] = pg.evaluate("scrollY")
            else: m["kind"] = "UNSCROLLED first viewport (scrollY=0)"
            pg.screenshot(path=str(out / m["file"])); res["shots"].append(m); pg.close()
    # real Save click
    pg = br.new_page(viewport={"width": 1648, "height": 1000}); pg.goto(f"{base}/market?{Q}")
    res["persistence"]["before_save"] = pg.evaluate(STATE); res["persistence"]["before_ids"] = pg.evaluate(VIS)
    pg.locator("#save-search summary").click(); form = pg.locator("#save-search form")
    form.locator("input[name=pin]").fill(PIN); form.locator("input[name=title]").fill("f137 real click"); form.locator("button[name=do]").click(); pg.wait_for_load_state()
    cid = json.loads((tmp / "c.json").read_text()) if (tmp / "c.json").exists() else None
    def reopen(b, tag):
        pg.goto(f"{b}/market"); link = pg.locator("a[href^='/market?run=']").first
        pg.goto(b + link.get_attribute("href")); pg.wait_for_load_state()      # the Run link sits in a closed disclosure: follow its href
        res["persistence"][tag] = {"url": pg.url, "controls": pg.evaluate(STATE), "ids": pg.evaluate(VIS), "scope": pg.inner_text("#location-scope")}
        pg.screenshot(path=str(out / f"{tag}.png"), full_page=False)
    reopen(base, "reopen")
    pr.terminate(); pr.wait(10)                                                                     # REAL process restart
    pr, base = start(); res["pid_after"] = pr.pid; reopen(base, "restart")
    br.close()
pr.terminate(); pr.wait(10)
P = res["persistence"]; want = {"mode": "state", "states": ["AR", "TX"], "also": True}
res["verdict"] = "PASS" if (P["before_save"] == want and P["reopen"]["controls"] == want and P["restart"]["controls"] == want and res["pid_before"] != res["pid_after"]
                            and P["before_ids"] == P["reopen"]["ids"] == P["restart"]["ids"] and len(P["before_ids"]) > 0) else "FAIL"
(out / "f137-evidence.json").write_text(json.dumps(res, indent=1)); print(res["verdict"], json.dumps(P)[:700])
