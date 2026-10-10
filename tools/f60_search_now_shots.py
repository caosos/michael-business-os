"""F-60: real-Chrome evidence that Search Now sits in the filter card and submits the real current values (click on desktop + mobile, Enter key).
Isolated staging: stub store, a COPY of the real GSA cache, loopback ephemeral port, DRY-RUN. usage: .venv/bin/python tools/f60_search_now_shots.py OUTDIR"""
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
code = {"sha": git("rev-parse", "HEAD"), "tree_dirty": bool(git("status", "--porcelain", "--", "operator_ui", "tests", "tools"))}
app = App(StubStore(), operator_pin="123456", campaigns_file=str(tmp / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"
START = "/market?go=1&base=Conway+AR&broad=1&radius=37.5"
KNOWN = "()=>[...document.querySelectorAll('.mk-g')].filter(c=>!c.closest('#unchecked-section')).map(c=>c.dataset.lot)"
POS = "()=>{const b=document.querySelector('button.mk-go').getBoundingClientRect(),f=document.querySelector('#mkfilters').getBoundingClientRect();return {button_top:Math.round(b.top+scrollY),button_bottom:Math.round(b.bottom+scrollY),inside_filter_card:b.top>=f.top&&b.bottom<=f.bottom,filter_card_top:Math.round(f.top+scrollY),viewport_h:innerHeight,button_in_first_viewport:b.top>=0&&b.bottom<=innerHeight}}"
log = []
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    for vname, w, h, how in (("desktop-1648x1000", 1648, 1000, "click"), ("mobile-390x844", 390, 844, "click"), ("desktop-1648x1000", 1648, 1000, "enter")):
        pg = br.new_page(viewport={"width": w, "height": h}); pg.goto(base + START)
        for step in ("before", "after"):
            if step == "after":
                pg.fill("#max_price", "25"); pg.fill("#min_price", "5")
                if how == "click":
                    pg.click("button.mk-go")
                else:
                    pg.focus("#max_price")
                    with pg.expect_navigation():
                        pg.keyboard.press("Enter")
                pg.wait_for_load_state()
            ids = pg.evaluate(KNOWN)
            meta = {"view": vname, "submit_by": how if step == "after" else "initial load", "step": step, "url": pg.url, "viewport": f"{w}x{h}", "port": httpd.server_address[1],
                    "filters_chips": pg.inner_text("#applied-filters"), "known_result_ids": ids, "known_count": len(ids), "unknown_section_ids": pg.evaluate("()=>[...document.querySelectorAll('#unchecked-section .mk-g')].map(c=>c.dataset.lot)"),
                    "typed_values": pg.evaluate("()=>({min:document.querySelector('#min_price').value,max:document.querySelector('#max_price').value,radius:document.querySelector('input[name=radius]').value})"),
                    "search_now": pg.evaluate(POS), "secondary_links": pg.evaluate("()=>[...document.querySelectorAll('nav[aria-label=Marketplace] a')].map(a=>a.textContent)"),
                    "code_sha": code["sha"], "operator_ui_tests_tools_dirty": code["tree_dirty"], "store": "STUB (no database)", "cache_sha256": real_sha, "cache_as_of_utc": asof,
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "browser": br.version}
            for kind, full in (("first-viewport", False), ("full-page", True)):
                fn = f"{vname}-{how}-{step}-{kind}.png"; pg.screenshot(path=str(out / fn), full_page=full); meta.setdefault("files", []).append(fn)
            log.append(meta)
        pg.close()
    br.close()
(out / "search-now-evidence.json").write_text(json.dumps(log, indent=1))
print(json.dumps([{k: m[k] for k in ("view", "submit_by", "step", "known_count", "typed_values", "search_now")} for m in log], indent=1))
