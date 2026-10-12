"""F-52 (C): preference learning for /market, deliberately small and explainable. Explicit actions only (save, not interested,
more/less like this), stored in a local JSON file, applied AFTER the hard filters (price, radius, terms), so it can reorder or hide
lots the owner dismissed but can never let a lot past a filter. No profitability is inferred, no outside data, no credentials.
Everything is DRY-RUN; there is no write path to anything but this file."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

ACTIONS = ("save", "unsave", "hide", "restore", "dismiss", "more", "less", "reset", "disable", "enable")
STOP = {"with", "from", "this", "that", "used", "lot", "item", "items", "unit", "units", "only", "each", "the", "and", "for", "set", "other"}
EMPTY = {"enabled": True, "saved": [], "dismissed": [], "hidden": {}, "more": {}, "less": {}, "last": {}, "bids": {}, "auto_stopped": [], "resale_targets": {}, "ui": {}}


def path() -> Path:
    return Path(os.environ.get("MBOS_MARKET_PREFS_FILE") or Path(__file__).resolve().parent.parent / "var" / "market_prefs.json")


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
    d["hidden"] = {**{i: "" for i in d["dismissed"]}, **d["hidden"]}      # older files kept hidden ids in `dismissed`
    d["dismissed"] = []
    return d


def _store(d: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent)
    with os.fdopen(fd, "w") as fh:
        json.dump(d, fh)
    os.replace(tmp, p)


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


def act(action: str, lot_id: str, title: str = "") -> str:
    if action not in ACTIONS:
        raise ValueError("unknown preference action")
    d = load()
    lot_id = re.sub(r"[^A-Za-z0-9._:-]", "", lot_id or "")[:200]
    if action == "reset":
        _store({"enabled": d["enabled"], "saved": [], "dismissed": [], "hidden": d["hidden"], "more": {}, "less": {}, "last": d.get("last") or {}, "bids": d["bids"], "auto_stopped": d["auto_stopped"], "resale_targets": d["resale_targets"], "ui": d.get("ui") if isinstance(d.get("ui"), dict) else {}})
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
        for t in terms(title):
            d["less"][t] = min(d["less"].get(t, 0) + 1, 5)
            d["more"].pop(t, None)
    else:
        tgt = d["more" if action == "more" else "less"]
        other = d["less" if action == "more" else "more"]
        for t in terms(title):
            tgt[t] = min(tgt.get(t, 0) + 1, 5)
            other.pop(t, None)
    _store(d)
    return {"save": "Saved.", "unsave": "Removed from saved.", "hide": "Hidden. Only this listing; nothing was learned. Restore it from the hidden list.",
            "restore": "Restored: this listing can appear again if it still matches your filters.",
            "dismiss": "Not interested: hidden, and its title words count as 'less like this'. Restoring it later does not undo that.",
            "more": "Noted: more like this.", "less": "Noted: less like this."}[action]


def summary(d: dict) -> str:
    return f"{len(d['saved'])} saved · {len(d['hidden'])} hidden · liked words: {', '.join(sorted(d['more'])) or 'none'} · disliked words: {', '.join(sorted(d['less'])) or 'none'}"


def hide(results: list[dict], d: dict) -> tuple[list[dict], int]:
    """Exact-ID hide, applied to every result section whether or not suggestions are on. Removes only; never adds or reorders."""
    keep = [c for c in results if c["id"] not in d["hidden"]]
    return keep, len(results) - len(keep)


def rank(results: list[dict], d: dict, key, reorder: bool = True) -> tuple[list[dict], int]:
    """-> (results, reordered only when `reorder`, with a visible `why` on each, number hidden as dismissed). Disabled: unchanged order, no why, nothing hidden."""
    if not d.get("enabled"):
        return results, 0
    out = []
    keep = results
    for c in keep:
        up = [t for t in terms(c["title"]) if t in d["more"]]
        dn = [t for t in terms(c["title"]) if t in d["less"]]
        score = (3 if c["id"] in d["saved"] else 0) + sum(d["more"][t] for t in up) - sum(d["less"][t] for t in dn)
        why = (["you saved it"] if c["id"] in d["saved"] else []) + ([f"matches words you liked ({', '.join(up)})"] if up else []) \
            + ([f"matches words you disliked ({', '.join(dn)})"] if dn else [])
        out.append((score, {**c, "why": "Why suggested: " + "; ".join(why) if why else None, "saved": c["id"] in d["saved"]}))
    if reorder:
        out.sort(key=lambda t: (-t[0], key(t[1])))
    return [c for _, c in out], 0
