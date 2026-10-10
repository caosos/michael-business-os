"""F-56: REAL Chrome clicks the REAL Save button (isolated staging, stub store, DRY-RUN, copy of the real GSA cache). Asserts cat/row1-4/condition reach the
saved search, then reopen + restart retention, comparing the VISIBLE known-section lot IDs (not inside <details>) with an independent computation.
usage: .venv/bin/python tools/f56_browser.py OUTDIR"""
import json, os, shutil, sys, tempfile, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["MBOS_MARKET_PREFS_FILE"] = str(tmp / "prefs.json")
REAL = Path(os.environ.get("F55_REAL_CACHE", "/home/michaelos/business-os-worktrees/agent-01-coordinator/var/cache/gsa-active-auctions.json"))
shutil.copy(REAL, tmp / "gsa.json"); shutil.copy(REAL.with_suffix(".asof"), tmp / "gsa.asof")
os.environ["MBOS_GSA_CACHE"] = str(tmp / "gsa.json")
from operator_ui import market_search as ms  # noqa: E402
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
PIN = "123456"


def boot():
    app = App(StubStore(), operator_pin=PIN, campaigns_file=str(tmp / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
    h = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=h.serve_forever, daemon=True).start()
    return app, h, f"http://127.0.0.1:{h.server_address[1]}"


VIS = """()=>[...document.querySelectorAll('.mk-g')].filter(c=>!c.closest('details')).map(c=>({lot:c.dataset.lot,row:(c.closest('[data-row]')||{dataset:{}}).dataset.row||null}))"""
Q = "go=1&base=Conway+AR&broad=1&radius=300&min_price=0&max_price=50000&cat=trailers&row1=equipment&row2=trailers&row3=&row4=&condition=trailer"
res = {"checks": {}}
app, h, base = boot()
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    pg = br.new_page(viewport={"width": 1648, "height": 1000}); pg.goto(f"{base}/market?{Q}")
    form = pg.locator("#save-search form"); pg.locator("#save-search summary").click()
    sent = {}
    pg.on("request", lambda r: sent.update(dict(x.split("=", 1) for x in (r.post_data or "").split("&"))) if r.method == "POST" else None)
    form.locator("input[name=pin]").fill(PIN); form.locator("input[name=title]").fill("f56 real click")
    form.locator("button[name=do]").click(); pg.wait_for_load_state()
    res["checks"]["post_fields_from_real_click"] = {k: sent.get(k) for k in ("cat", "row1", "row2", "row3", "row4", "condition")}
    nice = app.campaign_records()[0]["doc"]["criteria"]["nice_to_have"]; cid = app.campaign_records()[0]["doc"]["campaign_id"]
    res["checks"]["saved_nice_to_have"] = nice
    pg.goto(f"{base}/market?run={cid}")
    q = ms.parse_query({k: [v] for k, v in (kv.split("=") for kv in Q.split("&"))}); cards = ms.load_gsa(None, datetime.now(timezone.utc))["cards"]
    exp = ms.partition(cards, q)[0]
    got = pg.evaluate(VIS)
    res["checks"]["reopen"] = {"visible_known_ids": len(got), "expected": len(exp), "ids_equal": sorted(x["lot"] for x in got) == sorted(c["id"] for c in exp),
                                "chips": pg.inner_text("#applied-filters")}
    res["checks"]["reopen"]["rows_in_dom_order"] = [r for r in dict.fromkeys(x["row"] for x in got)]
    pg.screenshot(path=str(out / "reopen.png"), full_page=True)
    h.shutdown(); h.server_close()
    app2, h2, base2 = boot()                                                   # restart: a new process state over the same campaigns file
    pg.goto(f"{base2}/market?run={cid}")
    got2 = pg.evaluate(VIS)
    res["checks"]["restart"] = {"ids_equal": sorted(x["lot"] for x in got2) == sorted(c["id"] for c in exp), "visible_known_ids": len(got2), "chips": pg.inner_text("#applied-filters")}
    br.close()
c = res["checks"]
res["verdict"] = "PASS" if (c["post_fields_from_real_click"]["cat"] == "trailers" and c["post_fields_from_real_click"]["condition"] == "trailer" and c["post_fields_from_real_click"]["row1"] == "equipment"
                            and "cat:trailers" in c["saved_nice_to_have"] and "cond:trailer" in c["saved_nice_to_have"] and c["reopen"]["expected"] > 0 and c["reopen"]["ids_equal"] and c["restart"]["ids_equal"]) else "FAIL"
(out / "f56-browser.json").write_text(json.dumps(res, indent=1)); print(res["verdict"], json.dumps(res["checks"])[:900])
