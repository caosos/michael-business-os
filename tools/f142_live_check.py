"""F-142 post-reload check against a RUNNING UI (read-only: GET navigation only; never saves, never types the PIN).
usage: <python with playwright> tools/f142_live_check.py PORT [OUTDIR]
F-143 update: the price sliders were removed, so the 'below' test now covers the numeric price fields and the radius field. Asserts, at desktop 1648x1000 and mobile 390x844: Search Now is the last control in the filter card (after every input/select/summary),
below the price and radius fields, and that typing Min/Max then Search (click) and Enter changes the result set. Exit 0 = all pass, 1 = any fail."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

port, out = sys.argv[1], Path(sys.argv[2] if len(sys.argv) > 2 else ".")
out.mkdir(parents=True, exist_ok=True)
base = f"http://127.0.0.1:{port}"
START = "/market?go=1&base=Conway+AR&broad=1&radius=37.5"
KNOWN = "()=>[...document.querySelectorAll('.mk-g')].map(c=>c.dataset.lot)"  # every lot card on the page, checked or not-checked section
ORDER = ("()=>{const b=document.querySelector('button.mk-go');if(!b)return {ok:false,why:'no Search Now'};const r=b.getBoundingClientRect();"
         "const ctl=[...document.querySelectorAll('#mkfilters input:not([type=hidden]),#mkfilters select,#mkfilters summary')].filter(i=>i.getBoundingClientRect().height>0&&(i.tagName==='SUMMARY'||!i.closest('details:not([open])')));"
         "const after=ctl.filter(i=>i.getBoundingClientRect().top>r.top+1&&!i.closest('.st-list')).map(i=>i.name||i.textContent.trim().slice(0,20));"
         "const sl=['min_price','max_price','radius'].every(id=>{const e=document.getElementById(id);return e&&e.getBoundingClientRect().bottom<=r.top});"
         "return {ok:after.length===0&&sl,controls_below_button:after,below_price_and_radius:sl}}")
log, ok = [], True
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    for name, w, h, how in (("desktop", 1648, 1000, "click"), ("mobile", 390, 844, "click"), ("desktop", 1648, 1000, "enter")):
        pg = br.new_page(viewport={"width": w, "height": h}); pg.goto(base + START)
        before, order = pg.evaluate(KNOWN), pg.evaluate(ORDER)
        pg.fill("#max_price", "25"); pg.fill("#min_price", "5")
        if how == "click":
            pg.click("button.mk-go")
        else:
            pg.focus("#max_price")
            with pg.expect_navigation():
                pg.keyboard.press("Enter")
        pg.wait_for_load_state(); after = pg.evaluate(KNOWN)
        row = {"view": name, "submit_by": how, "order": order, "results_before": len(before), "results_after": len(after),
               "changed": before != after, "shot": f"live-{name}-{how}.png", "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        pg.screenshot(path=str(out / row["shot"]), full_page=True); log.append(row); pg.close()
        ok = ok and order.get("ok", False) and row["changed"]
    br.close()
(out / "live-check.json").write_text(json.dumps({"port": port, "pass": ok, "rows": log}, indent=1))
print(json.dumps({"port": port, "pass": ok, "rows": [{k: r[k] for k in ("view", "submit_by", "results_before", "results_after", "changed")} | {"order_ok": r["order"].get("ok"), "below": r["order"].get("controls_below_button")} for r in log]}, indent=1))
sys.exit(0 if ok else 1)
