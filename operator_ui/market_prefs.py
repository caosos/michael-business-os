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

ACTIONS = ("save", "unsave", "dismiss", "more", "less", "reset", "disable", "enable")
STOP = {"with", "from", "this", "that", "used", "lot", "item", "items", "unit", "units", "only", "each", "the", "and", "for", "set", "other"}
EMPTY = {"enabled": True, "saved": [], "dismissed": [], "more": {}, "less": {}, "last": {}}


def path() -> Path:
    return Path(os.environ.get("MBOS_MARKET_PREFS_FILE") or Path(__file__).resolve().parent.parent / "var" / "market_prefs.json")


def load() -> dict:
    try:
        d = json.loads(path().read_text())
        return {**EMPTY, **d} if isinstance(d, dict) else dict(EMPTY, saved=[], dismissed=[], more={}, less={}, last={})
    except (OSError, ValueError):
        return {"enabled": True, "saved": [], "dismissed": [], "more": {}, "less": {}, "last": {}}


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
    lot_id = re.sub(r"[^A-Za-z0-9._-]", "", lot_id or "")[:60]
    if action == "reset":
        _store({"enabled": d["enabled"], "saved": [], "dismissed": [], "more": {}, "less": {}, "last": d.get("last") or {}})
        return "Suggestions reset: saves, dismissals and likes were cleared."
    if action in ("disable", "enable"):
        d["enabled"] = action == "enable"
        _store(d)
        return "Suggestions are " + ("ON." if d["enabled"] else "OFF: results use your filters and sort only; your history is kept.")
    if not lot_id:
        raise ValueError("no lot given")
    if action == "save":
        d["saved"] = sorted(set(d["saved"]) | {lot_id})
        d["dismissed"] = [x for x in d["dismissed"] if x != lot_id]
    elif action == "unsave":
        d["saved"] = [x for x in d["saved"] if x != lot_id]
    elif action == "dismiss":
        d["dismissed"] = sorted(set(d["dismissed"]) | {lot_id})
        d["saved"] = [x for x in d["saved"] if x != lot_id]
    else:
        tgt = d["more" if action == "more" else "less"]
        other = d["less" if action == "more" else "more"]
        for t in terms(title):
            tgt[t] = min(tgt.get(t, 0) + 1, 5)
            other.pop(t, None)
    _store(d)
    return {"save": "Saved.", "unsave": "Removed from saved.", "dismiss": "Dismissed; it stays hidden until you reset.",
            "more": "Noted: more like this.", "less": "Noted: less like this."}[action]


def summary(d: dict) -> str:
    return f"{len(d['saved'])} saved · {len(d['dismissed'])} dismissed · liked words: {', '.join(sorted(d['more'])) or 'none'} · disliked words: {', '.join(sorted(d['less'])) or 'none'}"


def rank(results: list[dict], d: dict, key, reorder: bool = True) -> tuple[list[dict], int]:
    """-> (results, reordered only when `reorder`, with a visible `why` on each, number hidden as dismissed). Disabled: unchanged order, no why, nothing hidden."""
    if not d.get("enabled"):
        return results, 0
    keep = [c for c in results if c["id"] not in d["dismissed"]]
    out = []
    for c in keep:
        up = [t for t in terms(c["title"]) if t in d["more"]]
        dn = [t for t in terms(c["title"]) if t in d["less"]]
        score = (3 if c["id"] in d["saved"] else 0) + sum(d["more"][t] for t in up) - sum(d["less"][t] for t in dn)
        why = (["you saved it"] if c["id"] in d["saved"] else []) + ([f"matches words you liked ({', '.join(up)})"] if up else []) \
            + ([f"matches words you disliked ({', '.join(dn)})"] if dn else [])
        out.append((score, {**c, "why": "Why suggested: " + "; ".join(why) if why else None, "saved": c["id"] in d["saved"]}))
    if reorder:
        out.sort(key=lambda t: (-t[0], key(t[1])))
    return [c for _, c in out], len(results) - len(keep)
