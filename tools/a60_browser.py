"""A-60: isolated staging (stub store, COPY of real GSA cache, loopback, DRY-RUN). Real Chrome: click X, keyboard-operate X, restart process, Undo, screenshots.
usage: .venv/bin/python tools/a60_browser.py OUTDIR"""
import hashlib, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
from playwright.sync_api import sync_playwright  # noqa: E402

tmp = Path(tempfile.mkdtemp()); out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
REAL = Path(os.environ.get("F55_REAL_CACHE", "/home/michaelos/business-os-worktrees/agent-01-coordinator/var/cache/gsa-active-auctions.json"))
shutil.copy(REAL, tmp / "gsa.json"); shutil.copy(REAL.with_suffix(".asof"), tmp / "gsa.asof")
env = {**os.environ, "MBOS_STAGING_DIR": str(tmp), "MBOS_GSA_CACHE": str(tmp / "gsa.json")}
git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731


def start():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    pr = subprocess.Popen([sys.executable, str(ROOT / "tools/serve_market_staging.py"), str(port)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/market", timeout=1); break
        except Exception: time.sleep(0.1)
    return pr, f"http://127.0.0.1:{port}"


VIS = "()=>[...document.querySelectorAll('.mk-g')].filter(c=>!c.closest('#unchecked-section')).map(c=>c.dataset.lot)"
UNC = "()=>[...document.querySelectorAll('#unchecked-section .mk-g')].map(c=>c.dataset.lot)"
res = {"code_sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", "operator_ui", "tests", "tools")), "cache_sha256": hashlib.sha256(REAL.read_bytes()).hexdigest(),
       "cache_as_of": REAL.with_suffix(".asof").read_text().strip(), "store": "STUB", "steps": {}}
URL = "/market?go=1&base=Conway+AR&broad=1&radius=150&max_price=2000"
pr, base = start(); res["pid_before"] = pr.pid
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    pg = br.new_page(viewport={"width": 1648, "height": 1000}); pg.goto(base + URL)
    ids0 = pg.evaluate(VIS); unc0 = pg.evaluate(UNC); res["steps"]["before"] = {"checked": len(ids0), "unchecked": len(unc0)}
    pg.locator(".mk-g").first.scroll_into_view_if_needed(); pg.screenshot(path=str(out / "desktop-before.png"))
    pg.locator(f".mk-g[data-lot='{ids0[0]}'] .mk-x").click(); pg.wait_for_load_state()                      # real mouse click on X
    pg.goto(base + URL); ids1 = pg.evaluate(VIS); res["steps"]["after_click"] = {"hidden": ids0[0], "gone": ids0[0] not in ids1, "rest_same_order": ids1 == ids0[1:]}
    pg.locator(f".mk-g[data-lot='{ids1[0]}'] .mk-x").focus(); pg.keyboard.press("Enter"); pg.wait_for_load_state()   # keyboard-operated X
    pg.goto(base + URL); ids2 = pg.evaluate(VIS); res["steps"]["after_keyboard"] = {"hidden": ids1[0], "gone": ids1[0] not in ids2, "rest_same_order": ids2 == ids1[1:]}
    pg.locator("#unchecked-section summary").click()
    if unc0:
        pg.locator(f"#unchecked-section .mk-g[data-lot='{unc0[0]}'] .mk-x").click(); pg.wait_for_load_state()
        pg.goto(base + URL); res["steps"]["unchecked_hide"] = {"hidden": unc0[0], "gone": unc0[0] not in pg.evaluate(UNC)}
    for act in ("disable", "enable"):                                                                            # toggle independence
        pg.goto(base + URL); pg.locator("#prefs summary").click(); pg.locator(f"#prefs button[value={act}]").click(); pg.wait_for_load_state()
        pg.goto(base + URL); res["steps"][f"toggle_{act}"] = {"still_hidden": not ({ids0[0], ids1[0]} & set(pg.evaluate(VIS)))}
    pg.goto(base + URL); pg.locator("#hidden-list summary").click(); pg.evaluate("document.querySelector('#hidden-list').scrollIntoView()"); pg.screenshot(path=str(out / "desktop-hidden-list.png"))
    pr.terminate(); pr.wait(10); pr, base = start(); res["pid_after"] = pr.pid                                      # REAL restart
    pg.goto(base + URL); ids3 = pg.evaluate(VIS); res["steps"]["after_restart"] = {"hidden_still_gone": not ({ids0[0], ids1[0]} & set(ids3)), "same_as_before_restart": ids3 == ids2}
    pg.locator("#hidden-list summary").click(); pg.locator(f"#hidden-list li[data-hidden='{ids0[0]}'] button").click(); pg.wait_for_load_state()   # Undo one
    pg.goto(base + URL); ids4 = pg.evaluate(VIS); res["steps"]["undo_one"] = {"restored": ids0[0] in ids4, "other_still_hidden": ids1[0] not in ids4}
    pg.screenshot(path=str(out / "desktop-after-undo.png"))
    m = br.new_page(viewport={"width": 390, "height": 844}); m.goto(base + URL); m.locator(".mk-g").first.scroll_into_view_if_needed(); m.screenshot(path=str(out / "mobile-card-x.png"))
    m.evaluate("document.querySelector('#hidden-list').open=true; document.querySelector('#hidden-list').scrollIntoView()"); m.screenshot(path=str(out / "mobile-hidden-list.png"))
    # exhaustion on a tight filter
    T = "/market?go=1&base=Conway+AR&broad=1&radius=150&max_price=300"
    pg.goto(base + T)
    for i in pg.evaluate(VIS):
        pg.goto(base + T); pg.locator(f".mk-g[data-lot='{i}'] .mk-x").click(); pg.wait_for_load_state()
    pg.goto(base + T); res["steps"]["exhausted"] = {"text": pg.inner_text("#zero-results"), "cards_left": len(pg.evaluate(VIS))}
    pg.screenshot(path=str(out / "desktop-exhausted.png"))
    br.close()
res["prefs_file"] = json.loads((tmp / "prefs.json").read_text()); pr.terminate()
(out / "evidence.json").write_text(json.dumps(res, indent=1)); print(json.dumps(res["steps"], indent=1)[:3000]); print("dirty", res["dirty"])
