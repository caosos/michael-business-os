"""F-139: real-Chrome evidence for the read-only 'earlier decision' block on /market cards. Isolated staging: stub store, the committed test cache fixture,
a SYNTHETIC decision-case store in a temp dir (never the owner's var/private store), loopback ephemeral port, DRY-RUN.
usage: .venv/bin/python tools/f139_precedent_shots.py OUTDIR"""
import json, os, subprocess, sys, tempfile, threading, shutil
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ.update(MBOS_MARKET_PREFS_FILE=str(tmp / "prefs.json"), MBOS_DECISION_CASES_DIR=str(tmp / "cases"))
from tests.test_market_f47 import FIX, ASOF  # noqa: E402
shutil.copy(FIX, tmp / "gsa.json"); (tmp / "gsa.asof").write_text(ASOF.isoformat()); os.environ["MBOS_GSA_CACHE"] = str(tmp / "gsa.json")
from operator_ui import market_search as ms  # noqa: E402
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402
from tests.test_market_f139 import synth_case  # noqa: E402
from mbos import decision_cases as dc  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
private = ROOT / "var" / "private" / "decision_cases"
private_before = sorted(str(p) for p in private.rglob("*")) if private.exists() else None
app = App(StubStore(), operator_pin="123456", campaigns_file=str(tmp / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"
PATH = "/market?go=1&base=Conway+AR&broad=1&radius=150&max_price=100000"
cards = ms.partition(ms.load_gsa(None, ASOF)["cards"], ms.parse_query({"go": ["1"], "base": ["Conway AR"], "broad": ["1"], "radius": ["150"], "max_price": ["100000"]}))[0]
KNOWN = "()=>[...document.querySelectorAll('.mk-g')].filter(c=>!c.closest('#unchecked-section')).map(c=>c.dataset.lot)"
log = []
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    def visit(w, h, state, expand):
        pg = br.new_page(viewport={"width": w, "height": h}); pg.goto(base + PATH); pg.wait_for_load_state()
        ids = pg.evaluate(KNOWN); nblk = pg.evaluate("()=>document.querySelectorAll('[data-testid=precedent]').length")
        if expand and nblk:
            pg.locator("[data-testid=precedent] summary").first.click(); pg.locator("[data-testid=precedent]").first.scroll_into_view_if_needed()
        elif nblk:
            pg.locator("[data-testid=precedent]").first.scroll_into_view_if_needed()
        fn = f"{w}x{h}-{state}{'-expanded' if expand else ''}.png"; pg.screenshot(path=str(out / fn))
        note = pg.evaluate("()=>(document.querySelector('#precedent-note')||{}).innerText||''")
        log.append({"viewport": f"{w}x{h}", "store": state, "expanded": expand, "known_count": len(ids), "known_ids": ids, "precedent_blocks": nblk, "page_note": note, "file": fn}); pg.close()
    for (w, h) in ((1648, 1000), (390, 844)):
        visit(w, h, "no-store", False)
    f = tmp / "case.json"; f.write_text(json.dumps(synth_case(cards[0]))); dc.import_cases(f)
    for (w, h) in ((1648, 1000), (390, 844)):
        visit(w, h, "synthetic-store", False); visit(w, h, "synthetic-store", True)
    dc.set_enabled(False, "synthetic staging"); visit(1648, 1000, "synthetic-disabled", False)
    br.close()
private_after = sorted(str(p) for p in private.rglob("*")) if private.exists() else None
by = {m["viewport"]: m["known_ids"] for m in log if m["store"] == "no-store"}
iso = {"store_dir_used": os.environ["MBOS_DECISION_CASES_DIR"], "store_dir_is_inside_repo": str(ROOT) in os.environ["MBOS_DECISION_CASES_DIR"],
       "owner_private_store_untouched": private_before == private_after, "same_known_ids_with_and_without_store": all(m["known_ids"] == by[m["viewport"]] for m in log),
       "network": "none: loopback only, cache is the committed test fixture, nothing fetched",
       "code_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
       "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": "SYNTHETIC case only"}
(out / "evidence.json").write_text(json.dumps({"isolation": iso, "shots": log}, indent=1))
print(json.dumps(iso, indent=1)); print([(m["viewport"], m["store"], m["expanded"], m["known_count"], m["precedent_blocks"]) for m in log])
