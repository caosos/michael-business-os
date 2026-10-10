"""Provenance screenshots of the REAL /market page (no fixture, no stub): first viewport + full page, each with a metadata sidecar and a listing-ID check
against the actual GSA cache file. Run with a Python that has Playwright (the lane 06 venv) against an isolated staging server:

    ~/business-os-worktrees/agent-06-communications/.venv/bin/python tools/capture_market.py OUTDIR --sha 120e452 --port 8767

Nothing is faked or filtered: the page is whatever the code serves from the cache. DRY-RUN; GET only; no external navigation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse as U
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "var" / "cache" / "gsa-active-auctions.json"
SHOTS = [  # (name, label, query, viewport)
    ("conway-1648", "Realistic Conway search: default trailers/equipment focus, Conway AR, 150 mi", dict(go=1, source="gsa", base="Conway, AR", radius=150), (1648, 1000)),
    ("conway-390", "Same Conway search on a phone", dict(go=1, source="gsa", base="Conway, AR", radius=150), (390, 844)),
    ("broader-1648", "BROADER BROWSING EXAMPLE (not the Conway acceptance search): broad inventory mode, 300 mi", dict(go=1, source="gsa", base="Conway, AR", radius=300, broad=1), (1648, 1000)),
]


def cache_identity() -> dict:
    data = CACHE.read_bytes()
    asof = CACHE.with_suffix(".asof").read_text().strip()
    return {"path": str(CACHE), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "fetched_as_of": asof, "lots_in_file": len(json.loads(data)["Results"])}


def lots_by_id() -> dict:
    out = {}
    for r in json.loads(CACHE.read_bytes())["Results"]:
        m = re.search(r"/preview/(\d+)", r.get("itemDescURL") or "")
        if m:
            out[m.group(1)] = r
    return out


def _n(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _title_ok(shown: str, cached: str) -> bool:
    """Exact (whitespace-normalised), or a display truncation: the page ends with an ellipsis and what precedes it is a prefix of the cache title."""
    s, c = _n(shown), _n(cached)
    return s == c or (s.endswith("\u2026") and c.startswith(s[:-1].rstrip()))


def compare(page, lots: dict) -> dict:
    """Every displayed listing link must be a real cache lot's itemDescURL; checked cards must also show that lot's itemName (whitespace-normalised).
    The optional 'could not be checked' section is compared by link only (its markup has no title element)."""
    cards = page.evaluate("""()=>[...document.querySelectorAll('.mk-g')].map(g=>({title:(g.querySelector('.ti')||{}).innerText||'',
        link:(g.querySelector('a.listing-link')||{}).href||'', photo:!!g.querySelector('img'), tile:/behind GSA/.test(g.innerText),
        optional:!!g.closest('#unchecked-section')}))""")
    opt_links = page.evaluate("""()=>[...document.querySelectorAll('#unchecked-section a[href*="gsaauctions.gov"]')].map(a=>a.href)""")
    rows, bad = [], []
    for c in cards:
        if c["optional"]:
            continue
        m = re.search(r"/preview/(\d+)", c["link"])
        lot = lots.get(m.group(1)) if m else None
        ok = bool(lot) and c["link"].rstrip("/") == (lot["itemDescURL"] or "").rstrip("/") and _title_ok(c["title"], lot["itemName"])
        rows.append({"id": m.group(1) if m else None, "title": _n(c["title"])[:60], "link_and_title_match_cache": ok, "photo_img": c["photo"], "login_tile": c["tile"]})
        if not ok:
            bad.append(rows[-1])
    obad = [l for l in opt_links if not (re.search(r"/preview/(\d+)", l) and re.search(r"/preview/(\d+)", l).group(1) in lots)]
    return {"checked_cards": len(rows), "checked_all_match_cache": not bad and bool(rows), "checked_mismatches": bad[:5], "optional_section_links": len(opt_links),
            "optional_all_in_cache": not obad, "optional_mismatches": obad[:5], "listings": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--sha", required=True)
    ap.add_argument("--port", type=int, default=8767)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ident, lots = cache_identity(), lots_by_id()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        for name, label, q, (w, h) in SHOTS:
            url = f"http://127.0.0.1:{a.port}/market?{U.urlencode(q)}"
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.goto(url)
            pg.wait_for_load_state("networkidle")
            meta = {"label": label, "code_sha": a.sha, "url": url, "port": a.port, "viewport": f"{w}x{h}", "active_filters": q,
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source_cache": ident,
                    "page_states_cache_time": ("last fetched " + datetime.fromisoformat(ident["fetched_as_of"]).strftime("%Y-%m-%d %H:%M") + " UTC") in pg.inner_text("body"),
                    "page_says_cached_not_fresh": "not a fresh fetch" in pg.inner_text("body"),
                    "first_card_top_px": pg.evaluate("()=>{const g=document.querySelector('.mk-g');return g?Math.round(g.getBoundingClientRect().top+scrollY):null}"),
                    "horizontal_overflow": pg.evaluate("()=>document.documentElement.scrollWidth>document.documentElement.clientWidth"),
                    "b19_comparison_with_cache": compare(pg, lots), "fixture": "NONE: real cache file, real server code, no stub store"}
            pg.screenshot(path=str(out / f"{name}-first-viewport.png"))
            pg.screenshot(path=str(out / f"{name}-full-page.png"), full_page=True)
            (out / f"{name}.json").write_text(json.dumps(meta, indent=1))
            c = meta["b19_comparison_with_cache"]
            print(name, w, h, "checked cards", c["checked_cards"], "match", c["checked_all_match_cache"], "| optional links", c["optional_section_links"], "in cache", c["optional_all_in_cache"],
                  "first card top", meta["first_card_top_px"], "overflow", meta["horizontal_overflow"])
            pg.close()
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
