"""F-55: REAL-CACHE visual evidence (isolated staging, stub store, DRY-RUN, read-only on a COPY of the existing GSA cache, no external navigation).
Per scenario: first-viewport + full-page screenshot at desktop and 390px, one metadata JSON per screenshot, B19 comparison of displayed lot IDs/links/titles against the cache.
usage: .venv/bin/python tools/f55_real_cache_shots.py OUTDIR   (re-run periodically for the recurring Arya review)"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["MBOS_MARKET_PREFS_FILE"] = str(tmp / "prefs.json")
REAL = Path(os.environ.get("F55_REAL_CACHE", "/home/michaelos/business-os-worktrees/agent-01-coordinator/var/cache/gsa-active-auctions.json"))
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
real_sha, asof = sha(REAL), REAL.with_suffix(".asof").read_text().strip()
shutil.copy(REAL, tmp / "gsa.json"); shutil.copy(REAL.with_suffix(".asof"), tmp / "gsa.asof")   # the page reads a copy; the original is never opened for write
os.environ["MBOS_GSA_CACHE"] = str(tmp / "gsa.json")
from operator_ui.server import App, make_handler  # noqa: E402
from tests.test_wanted_f23 import GOV_POLICY, StubStore  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731
code = {"sha": git("rev-parse", "HEAD"), "tree_dirty": bool(git("status", "--porcelain", "--", "operator_ui", "data")), "branch": git("rev-parse", "--abbrev-ref", "HEAD")}
raw = json.loads(REAL.read_text())["Results"]
by_id = {f"{r['saleNo']}-{r['lotNo']}": r for r in raw}
app = App(StubStore(), operator_pin="123456", campaigns_file=str(tmp / "c.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app)); threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"
SCEN = [  # (slug, label, query)
    ("s1-conway-trailer", "REALISTIC SEARCH: origin Conway AR, keyword 'trailer', radius 150 mi, max price $5,000, trailers/equipment focus", "go=1&base=Conway+AR&keywords=trailer&radius=150&max_price=5000"),
    ("s2-conway-tight", "TIGHT SEARCH (may match nothing, shown as-is): Conway AR, keyword 'trailer', radius 25 mi, max price $1,000", "go=1&base=Conway+AR&keywords=trailer&radius=25&max_price=1000"),
    ("s3-broad-browse", "BROADER BROWSING EXAMPLE (separately labelled, not the realistic search): Conway AR, all categories (broad mode), radius 150 mi, no price limit", "go=1&base=Conway+AR&broad=1&radius=150"),
]
VIEWS = [("desktop-1648x1000", 1648, 1000), ("mobile-390x844", 390, 844)]
DOM = """()=>[...document.querySelectorAll('.mk-g')].map(c=>({lot:c.dataset.lot,in_unchecked_or_closed_section:!!c.closest('details'),title:(c.querySelector('.ti b')||{}).textContent,hrefs:[...c.querySelectorAll('a[href]')].map(a=>a.href)}))"""
index, b19 = [], {}
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    ver = br.version
    for slug, label, q in SCEN:
        for vname, w, h in VIEWS:
            pg = br.new_page(viewport={"width": w, "height": h}); url = base + "/market?" + q
            pg.goto(url); pg.wait_for_load_state()
            cards = pg.evaluate(DOM); chips = pg.inner_text("#applied-filters") if pg.query_selector("#applied-filters") else ""
            src_line = " ".join(pg.inner_text(".mk-main").split())[:400]
            for kind, full in (("first-viewport", False), ("full-page", True)):
                fn = f"{slug}-{vname}-{kind}.png"; pg.screenshot(path=str(out / fn), full_page=full)
                meta = {"file": fn, "scenario": label, "evidence_class": "REAL_CACHE" if slug != "s3-broad-browse" else "REAL_CACHE_BROADER_BROWSING_EXAMPLE",
                        "code_sha": code["sha"], "branch": code["branch"], "operator_ui_tree_dirty": code["tree_dirty"], "url": url, "viewport": f"{w}x{h}", "capture": kind,
                        "active_filters_chips": chips, "source": "GSA Auctions cached active-auctions file (no live fetch)", "cache_original_path": str(REAL), "cache_sha256": real_sha,
                        "cache_as_of_utc": asof, "cache_lots_total": len(raw), "cards_in_dom": len(cards), "cards_in_open_sections": sum(not c["in_unchecked_or_closed_section"] for c in cards),
                        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "browser": ver, "page_text_head": src_line, "fabricated_listings": False, "photos": "placeholders only (GSA cache carries none)"}
                (out / (fn[:-4] + ".json")).write_text(json.dumps(meta, indent=1)); index.append(meta)
            if vname.startswith("desktop"):
                ids = [c["lot"] for c in cards]
                mism = {"unknown_ids": [i for i in ids if i not in by_id], "duplicate_ids": sorted({i for i in ids if ids.count(i) > 1}), "link_mismatch": [], "title_mismatch": []}
                for c in cards:
                    r = by_id.get(c["lot"])
                    if not r:
                        continue
                    ext = [x for x in c["hrefs"] if not x.startswith(base)]
                    if any(x != r["itemDescURL"] for x in ext) or not ext:
                        mism["link_mismatch"].append({"lot": c["lot"], "page": ext, "cache": r["itemDescURL"]})
                    norm = lambda t: " ".join((t or "").split())  # noqa: E731  (HTML collapses runs of spaces)
                    if norm(c["title"]) != norm(r["itemName"]) and not norm(r["itemName"]).startswith(norm(c["title"]).rstrip("…. ")):
                        mism["title_mismatch"].append({"lot": c["lot"], "page": c["title"], "cache": r["itemName"]})
                b19[slug] = {"query": q, "displayed": len(ids), "unique": len(set(ids)), **mism, "pass_fidelity": not any(mism.values())}
    br.close()
verdict = "PASS (fidelity)" if all(v["pass_fidelity"] for v in b19.values()) and b19 else "UNVERIFIED"
(out / "b19-comparison.json").write_text(json.dumps({"verdict": verdict, "scope": "every displayed lot ID exists in the cache copy, appears once, its original link equals the cache itemDescURL, and its title matches the cache itemName. Completeness of the filtered set is covered by F-54's set-equality run, not recomputed here.", "cache_sha256": real_sha, "cache_as_of_utc": asof, "code": code, "scenarios": b19}, indent=1))
(out / "index.json").write_text(json.dumps(index, indent=1)); print(verdict, json.dumps({k: (v["displayed"], v["pass_fidelity"]) for k, v in b19.items()}), "sha", code)
