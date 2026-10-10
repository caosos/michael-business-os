"""Browser proof: a real Save click, reopen, and a real PROCESS RESTART retain categories, condition and custom row order on /market.

    ~/business-os-worktrees/agent-06-communications/.venv/bin/python tools/accept_save_restart.py EXPORT_DIR OUTDIR --sha SHA

What is real: the operator_ui code of the exported commit, the real cached GSA file, real Chrome, a real Save (CSRF + PIN) through the rendered form,
a real OS-process kill and restart. What is NOT real: the decision-queue database. The server uses a STUB store with its own PIN, campaigns file and
prefs file (tools/accept_serve.py), so this proves the saved-search/prefs persistence layers, not database persistence. Nothing touches the live :8766.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PORT, PIN = 8771, "123456"
WANT = {"cats": ["trailers", "vehicles"], "rows": ["vehicles", "trailers", "tools", "electronics"], "condition": "trailer"}   # scenario A: categories checked
WANT_C = {"cats": [], "rows": None, "condition": "", "any": "utility"}   # scenario C: ONLY an any-of term that visibly narrows the results
WANT_B = {"cats": [], "rows": ["vehicles", "trailers", "tools", "electronics"], "condition": "trailer"}   # scenario B: no category checked, custom rows drive the order


def start(export: Path, state: Path) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, str(HERE / "accept_serve.py"), str(export), str(state), str(PORT)], stdout=subprocess.DEVNULL, stderr=open(state.parent / "server-stderr.log", "a"),
                         env={**os.environ, "MBOS_CONTRACTS_DIR": str(HERE.parent / "docs" / "research" / "contracts")})
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/market", timeout=2).read(1)
            return p
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("isolated server did not start")


def read_state(pg) -> dict:
    return pg.evaluate("""()=>({cats:[...document.querySelectorAll("input[name=cat]:checked")].map(i=>i.value),
        rows:[1,2,3,4].map(n=>{const s=document.querySelector("select[name=row"+n+"]");return s?s.value:null}),
        condition:(document.querySelector("input[name=condition][size]")||{}).value||'',
        row_sections_in_dom_order:[...document.querySelectorAll('.mk-row')].map(r=>r.dataset.row),
        chips:(document.querySelector('.mk-chips')||{innerText:''}).innerText.replace(/\\s+/g,' '),
        visible_known_ids:[...document.querySelectorAll('.mk-g')].filter(g=>!g.closest('#unchecked-section')).map(g=>{const a=g.querySelector('a.listing-link');const m=a&&a.href.match(/preview\\/(\\d+)/);return m?m[1]:null}).filter(Boolean).sort()})""")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("out")
    ap.add_argument("--sha", required=True)
    ap.add_argument("--scenario", choices=("A", "B", "C"), default="A")
    a = ap.parse_args()
    global WANT
    WANT = WANT_B if a.scenario == "B" else WANT_C if a.scenario == "C" else WANT
    out, export = Path(a.out), Path(a.export)
    out.mkdir(parents=True, exist_ok=True)
    state = out / "state"
    if state.exists():
        for f in state.glob("*"):
            f.unlink()
    log = {"scenario": a.scenario, "code_sha": a.sha, "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "wanted": WANT,
           "what_is_real": "operator_ui code at the SHA, real cached GSA file, real Chrome, real Save click with CSRF+PIN, real OS-process restart",
           "what_is_not_real": "decision-queue database: STUB store, isolated campaigns+prefs files (database persistence NOT proven by this run)"}
    srv = start(export, state)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            pg = b.new_page(viewport={"width": 1648, "height": 1000})
            base = f"http://127.0.0.1:{PORT}"
            pg.goto(base + "/market?new=1")
            pg.evaluate("()=>document.querySelectorAll('details').forEach(d=>{d.open=true})")   # a user expanding the filter / row disclosures
            for c in WANT["cats"]:
                pg.check(f"input[name=cat][value={c}]")
            if WANT["rows"] is None:                                                    # scenario C: narrow only by the any-of term
                pg.fill("input[name=any]:not([type=hidden])", WANT["any"])
                pg.check("input[name=broad]") if False else None
            else:
                for i, r in enumerate(WANT["rows"], 1):
                    pg.select_option(f"select[name=row{i}]", r)
                pg.fill("input[name=condition][size]", WANT["condition"])
            pg.fill("input[name=max_price]:not([type=hidden])", "5000")                        # Save needs a price limit
            if WANT["rows"] is None:
                base_pg = b.new_page(viewport={"width": 1648, "height": 1000})
                base_pg.goto(base + "/market?go=1&source=gsa&base=Conway%2C+AR&radius=150&max_price=5000")
                base_pg.wait_for_load_state("networkidle")
                log["unfiltered_visible_ids"] = read_state(base_pg)["visible_known_ids"]
                base_pg.close()
            pg.click("button.mk-go")
            pg.wait_for_load_state("networkidle")
            log["after_search"] = read_state(pg)
            pg.evaluate("()=>{const d=document.querySelector('#save-search');if(d)d.open=true}")   # the user opens the Save disclosure
            pg.fill("#save-search input[name=title]", "Acceptance scenario " + a.scenario)
            pg.fill("#save-search input[name=pin]", PIN)
            pg.screenshot(path=str(out / "01-before-save.png"))
            with pg.expect_navigation():
                pg.click("#save-search form button")
            pg.wait_for_load_state("networkidle")
            log["save_message"] = re.sub(r"\s+", " ", pg.inner_text(".msg, .notice, [role=status]") if pg.query_selector(".msg, .notice, [role=status]") else "")[:160]
            link = pg.query_selector("a[href*='run='], a[href*='edit=']")
            log["saved_link"] = link.get_attribute("href") if link else None
            if not link:
                raise RuntimeError("no saved-search link after Save; url=" + pg.url + "; messages: " + " | ".join(re.findall(r"[^.|]{0,60}(?:Saved|saved|PIN|pin|required|refused|error|Error|Name|name)[^.|]{0,80}", re.sub(r"\s+", " ", pg.inner_text("body")))[:6]))
            href = link.get_attribute("href")
            pg.goto(base + href)
            pg.wait_for_load_state("networkidle")
            log["after_reopen"] = read_state(pg)
            pg.screenshot(path=str(out / "02-after-reopen.png"))
            srv.terminate()
            srv.wait(timeout=10)
            log["server_killed_pid"] = srv.pid
            srv = start(export, state)
            log["server_restarted_pid"] = srv.pid
            pg2 = b.new_page(viewport={"width": 1648, "height": 1000})
            pg2.goto(base + href)
            pg2.wait_for_load_state("networkidle")
            log["after_process_restart"] = read_state(pg2)
            pg2.screenshot(path=str(out / "03-after-process-restart.png"))
            pg2.goto(base + "/market")
            log["plain_load_after_restart"] = read_state(pg2)
            b.close()
    finally:
        srv.terminate()
    ok = {}
    for k in ("after_reopen", "after_process_restart"):
        s = log[k]
        if WANT["rows"] is None:
            ok[k] = True            # scenario C compares the applied mode and the visible known IDs below
        else:
            ok[k] = sorted(s["cats"]) == sorted(WANT["cats"]) and s["rows"] == WANT["rows"] and s["condition"] == WANT["condition"]
    if WANT["rows"] is None:
        ok["narrowed"] = bool(log["after_search"]["visible_known_ids"]) and "focus: " + WANT["any"] in log["after_search"]["chips"] and bool(log.get("unfiltered_visible_ids")) \
            and log["after_search"]["visible_known_ids"] != log["unfiltered_visible_ids"]
        log["any_term_narrows_visible_results"] = {"with_any": len(log["after_search"]["visible_known_ids"]), "without_any": len(log.get("unfiltered_visible_ids") or [])}
    dom = [r for r in log["after_process_restart"]["row_sections_in_dom_order"] if r != "other"]
    mode = lambda st: (re.search(r"Mode:.*?(?=Max price|Min price|Condition|$)", st["chips"]) or [""])[0].strip()
    same_mode = {k: mode(log[k]) == mode(log["after_search"]) for k in ("after_reopen", "after_process_restart")}
    same_ids = {k: log[k]["visible_known_ids"] == log["after_search"]["visible_known_ids"] for k in ("after_reopen", "after_process_restart")}
    ok["applied_focus_unchanged"] = all(same_mode.values())
    ok["visible_known_ids_unchanged"] = all(same_ids.values())
    log["verdict"] = {"applied_mode_before_save": mode(log["after_search"]), "applied_mode_after_reopen": mode(log["after_reopen"]), "applied_mode_after_restart": mode(log["after_process_restart"]),
                      "applied_focus_unchanged_after_reopen_and_restart": ok["applied_focus_unchanged"], "visible_known_ids_unchanged_after_reopen_and_restart": ok["visible_known_ids_unchanged"],
                      "scenario": a.scenario, "reopen_retains_categories_rows_condition": ok["after_reopen"], "restart_retains_categories_rows_condition": ok["after_process_restart"],
                      "displayed_section_order_after_restart": dom,
                      "displayed_order_equals_chosen_rows": ("n/a (scenario C)" if WANT["rows"] is None else (dom == [r for r in WANT["rows"] if r] if not WANT["cats"] else "n/a (checked categories replace the row slots by design)")),
                      "any_term_narrows_visible_results": log.get("any_term_narrows_visible_results")}
    if not WANT["cats"] and WANT["rows"] is not None:
        ok["displayed_order"] = dom == [r for r in WANT["rows"] if r]
    (out / "save-restart.json").write_text(json.dumps(log, indent=1))
    print(json.dumps(log["verdict"], indent=1))
    return 0 if all(ok.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
