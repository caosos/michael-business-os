"""F-52 (C): preference learning for /market, deliberately small and explainable. Explicit actions only (save, not interested,
more/less like this), stored in a local JSON file, applied AFTER the hard filters (price, radius, terms), so it can reorder or hide
lots the owner dismissed but can never let a lot past a filter. No profitability is inferred, no outside data, no credentials.
Everything is DRY-RUN; there is no write path to anything but this file."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from . import accounts

ACTIONS = ("save", "unsave", "hide", "restore", "dismiss", "more", "less", "reset", "disable", "enable")
STOP = {"with", "from", "this", "that", "used", "lot", "item", "items", "unit", "units", "only", "each", "the", "and", "for", "set", "other"}
EMPTY = {"enabled": True, "saved": [], "dismissed": [], "hidden": {}, "more": {}, "less": {},
         "more_categories": {}, "less_categories": {}, "more_sources": {}, "less_sources": {},
         "last": {}, "bids": {}, "auto_stopped": [], "resale_targets": {}, "ui": {}}
DISCOVERY_MAX = 2                 # at most two deliberate discovery cards in the leading result page
DISCOVERY_PAGE_SIZE = 12
_LOCK = threading.RLock()


def path() -> Path:
    local = Path(os.environ.get("MBOS_MARKET_PREFS_FILE") or Path(__file__).resolve().parent.parent / "var" / "market_prefs.json")
    return accounts.preference_path(local)


def load() -> dict:
    try:
        d = json.loads(path().read_text())
        d = {**EMPTY, **d} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        d = {}
    d = {**{k: (type(v)() if isinstance(v, (list, dict)) else v) for k, v in EMPTY.items()}, **d}
    if not isinstance(d["hidden"], dict):
        d["hidden"] = {}
    if not isinstance(d["bids"], dict):
        d["bids"] = {}
    if not isinstance(d["resale_targets"], dict):
        d["resale_targets"] = {}
    if not isinstance(d["auto_stopped"], list):
        d["auto_stopped"] = []
    for k in ("more", "less", "more_categories", "less_categories", "more_sources", "less_sources"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    # Conway is the existing local owner's starting point, not a default for
    # every future account.  A newly authenticated user begins unlocated and
    # supplies their own city/ZIP before a radius search can run.
    ui = d.get("ui") if isinstance(d.get("ui"), dict) else {}
    if accounts.current().authenticated and not isinstance(ui.get("home"), dict):
        d["ui"] = {**ui, "home": {"state": "", "zip": "", "label": ""}}
    d["hidden"] = {**{i: "" for i in d["dismissed"]}, **d["hidden"]}      # older files kept hidden ids in `dismissed`
    d["dismissed"] = []
    return d


def _store(d: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if accounts.current().authenticated:
        p.parent.chmod(0o700)
    with _LOCK:
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".market-prefs-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, p)
            p.chmod(0o600)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def recall(keys) -> dict:
    """F-53: the owner's last filter/category/row-order choices, restored after a server restart. Only known filter keys, only lists of short strings."""
    last = load().get("last")
    if not isinstance(last, dict):
        return {}
    return {k: [str(x)[:200] for x in v][:12] for k, v in last.items() if k in keys and isinstance(v, list)}


def remember(given: dict) -> None:
    d = load()
    d["last"] = given
    _store(d)


def terms(title: str) -> list[str]:
    return sorted({w for w in re.findall(r"[a-z]{4,}", (title or "").lower()) if w not in STOP})[:8]


def _categories(raw: str) -> list[str]:
    """Canonical, bounded category keys supplied by the rendered listing card."""
    return sorted({v for v in str(raw or "").split(",") if re.fullmatch(r"[a-z0-9_]{1,40}", v)})[:8]


def _source(raw: str) -> str:
    """A stable non-display source token; arbitrary form text never becomes a key."""
    return re.sub(r"[^a-z0-9]+", "_", str(raw or "").lower()).strip("_")[:80]


def _learn(d: dict, direction: str, title: str, category: str, source: str) -> None:
    """Record only explicit More/Less feedback, with small capped weights."""
    other = "less" if direction == "more" else "more"
    for t in terms(title):
        d[direction][t] = min(d[direction].get(t, 0) + 1, 5)
        d[other].pop(t, None)
    for cat in _categories(category):
        tgt, opposite = d[f"{direction}_categories"], d[f"{other}_categories"]
        tgt[cat] = min(tgt.get(cat, 0) + 1, 5)
        opposite.pop(cat, None)
    src = _source(source)
    if src:
        tgt, opposite = d[f"{direction}_sources"], d[f"{other}_sources"]
        tgt[src] = min(tgt.get(src, 0) + 1, 5)
        opposite.pop(src, None)


def act(action: str, lot_id: str, title: str = "", category: str = "", source: str = "") -> str:
    if action not in ACTIONS:
        raise ValueError("unknown preference action")
    d = load()
    lot_id = re.sub(r"[^A-Za-z0-9._:-]", "", lot_id or "")[:200]
    if action == "reset":
        _store({"enabled": d["enabled"], "saved": [], "dismissed": [], "hidden": d["hidden"], "more": {}, "less": {},
                "more_categories": {}, "less_categories": {}, "more_sources": {}, "less_sources": {},
                "last": d.get("last") or {}, "bids": d["bids"], "auto_stopped": d["auto_stopped"],
                "resale_targets": d["resale_targets"], "ui": d.get("ui") if isinstance(d.get("ui"), dict) else {}})
        return "Suggestions reset: saves and likes were cleared. Hidden listings stay hidden; restore them one by one from the hidden list."
    if action in ("disable", "enable"):
        d["enabled"] = action == "enable"
        _store(d)
        return "Suggestions are " + ("ON." if d["enabled"] else "OFF: results use your filters and sort only; your history is kept.")
    if not lot_id:
        raise ValueError("no lot given")
    if action == "save":
        d["saved"] = sorted(set(d["saved"]) | {lot_id})
        d["hidden"].pop(lot_id, None)
    elif action == "unsave":
        d["saved"] = [x for x in d["saved"] if x != lot_id]
    elif action == "hide":                           # X: this exact listing only; no learning weights, saved records untouched
        d["hidden"][lot_id] = (title or "")[:120]
    elif action == "restore":                        # only this listing; saves, likes and learned words stay as they are
        d["hidden"].pop(lot_id, None)
    elif action == "dismiss":                        # Not interested: hides this listing AND counts as 'less like this' for its title words
        d["hidden"][lot_id] = (title or "")[:120]
        _learn(d, "less", title, category, source)
    else:
        _learn(d, action, title, category, source)
    _store(d)
    return {"save": "Saved.", "unsave": "Removed from saved.", "hide": "Hidden. Only this listing; nothing was learned. Restore it from the hidden list.",
            "restore": "Restored: this listing can appear again if it still matches your filters.",
            "dismiss": "Not interested: hidden, and its title words count as 'less like this'. Restoring it later does not undo that.",
            "more": "Noted: more like this.", "less": "Noted: less like this."}[action]


def summary(d: dict) -> str:
    liked = len(d.get("more_categories") or {}) + len(d.get("more_sources") or {})
    disliked = len(d.get("less_categories") or {}) + len(d.get("less_sources") or {})
    extra = f" · category/source signals: {liked} more, {disliked} less" if liked or disliked else ""
    return (f"{len(d['saved'])} saved · {len(d['hidden'])} hidden · liked words: {', '.join(sorted(d['more'])) or 'none'} "
            f"· disliked words: {', '.join(sorted(d['less'])) or 'none'}{extra}")


def hide(results: list[dict], d: dict) -> tuple[list[dict], int]:
    """Exact-ID hide, applied to every result section whether or not suggestions are on. Removes only; never adds or reorders."""
    keep = [c for c in results if c["id"] not in d["hidden"]]
    return keep, len(results) - len(keep)


def rank(results: list[dict], d: dict, key, reorder: bool = True) -> tuple[list[dict], int]:
    """Explain and optionally reorder an already-filtered list.

    This function cannot add a row: location/radius/category/source and other
    hard filters run before it.  With learned signals, at most two neutral rows
    are deliberately lifted into the first 12 as discovery; all choices are
    deterministic so refreshes and tests do not shuffle a user's feed.
    """
    if not d.get("enabled"):
        return results, 0
    more_c, less_c = d.get("more_categories", {}), d.get("less_categories", {})
    more_s, less_s = d.get("more_sources", {}), d.get("less_sources", {})
    has_any_learning = bool(d.get("saved") or d.get("more") or d.get("less") or more_c or less_c or more_s or less_s)
    out = []
    for c in results:
        up = [t for t in terms(c["title"]) if t in d["more"]]
        dn = [t for t in terms(c["title"]) if t in d["less"]]
        cats = sorted(__import__("operator_ui.market_search", fromlist=["x"]).card_cats(c))
        cup = [v for v in cats if v in more_c]
        cdn = [v for v in cats if v in less_c]
        src = _source(c.get("source") or c.get("source_key") or "")
        sup = [src] if src in more_s else []
        sdn = [src] if src in less_s else []
        score = ((3 if c["id"] in d["saved"] else 0) + sum(d["more"][t] for t in up) - sum(d["less"][t] for t in dn)
                 + 2 * sum(more_c[t] for t in cup) - 2 * sum(less_c[t] for t in cdn)
                 + sum(more_s[t] for t in sup) - sum(less_s[t] for t in sdn))
        why = (["you saved it"] if c["id"] in d["saved"] else []) + ([f"matches words you liked ({', '.join(up)})"] if up else []) \
            + ([f"matches categories you liked ({', '.join(cup)})"] if cup else []) + (["comes from a source you liked"] if sup else []) \
            + ([f"matches words you disliked ({', '.join(dn)})"] if dn else []) + ([f"matches categories you disliked ({', '.join(cdn)})"] if cdn else []) \
            + (["comes from a source you disliked"] if sdn else [])
        text = "; ".join(why) if why else "matches your current filters; no preference signal yet"
        explanation = "Why you're seeing this: " + text + "." if has_any_learning else None
        out.append((score, {**c, "why": explanation, "saved": c["id"] in d["saved"], "discovery": False}))
    if reorder and out:
        positive = sorted((x for x in out if x[0] > 0), key=lambda t: (-t[0], key(t[1])))
        neutral = sorted((x for x in out if x[0] == 0), key=lambda t: key(t[1]))
        negative = sorted((x for x in out if x[0] < 0), key=lambda t: (-t[0], key(t[1])))
        has_learning = bool(positive or negative)
        take = min(DISCOVERY_MAX, len(neutral)) if has_learning else 0
        discoveries = []
        for score, card in neutral[:take]:
            card = {**card, "discovery": True,
                    "why": f"Why you're seeing this: discovery pick ({len(discoveries) + 1} of up to {DISCOVERY_MAX}); it matches your current filters."}
            discoveries.append((score, card))
        # The deliberate discovery set is bounded. If the feed has fewer
        # learned matches, remaining neutral rows still follow in normal order.
        out = positive[:max(0, DISCOVERY_PAGE_SIZE - take)] + discoveries + positive[max(0, DISCOVERY_PAGE_SIZE - take):] + neutral[take:] + negative
    return [c for _, c in out], 0
