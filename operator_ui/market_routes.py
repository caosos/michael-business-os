"""F-47: the two thin entry points server.py calls for /market (GET page, POST save/edit/enable/disable). Saved searches go through
App.wanted_change, so the Wanted model, its history rows, CSRF + PIN and receipts are reused; no second datastore."""

from __future__ import annotations

import os
from urllib.parse import quote

from . import market_search as ms
from . import market_view as mv
from .ux import InputError


def _saved(app) -> list[dict]:
    out = []
    for r in app.campaign_records():
        d = r.get("doc") if isinstance(r, dict) else None
        if isinstance(d, dict) and (d.get("criteria") or {}).get("category") == mv.CATEGORY:
            out.append(r)
    return out


def page_body(app, qs: dict, now, errors=None, values=None) -> str:
    saved = _saved(app)
    ids = {r["doc"]["campaign_id"]: r["doc"] for r in saved}
    pick = (qs.get("run") or qs.get("edit") or [None])[0]
    if values is not None:
        q = ms.parse_query({k: [v] for k, v in values.items()})
    elif pick in ids:
        q = ms.parse_query({k: [str(v)] for k, v in ms.criteria_to_query(ids[pick]).items()})
    else:
        q = ms.parse_query(qs)
    edit = (qs.get("edit") or [None])[0]
    ran = bool(qs.get("go") or qs.get("run")) and not qs.get("new")
    data = ms.load_gsa(os.environ.get("MBOS_GSA_CACHE") or None, now, ms._origin(q["base"])) if q["source"] == "gsa" or not ran else \
        {"status": "connected", "as_of": None, "age_h": 0, "stale": False, "in_scope": 0, "in_file": 0, "cards": [], "message": ""}
    results, hidden = ms.search(data["cards"], q) if ran and data["status"] == "connected" else ([], {})
    return mv.render_page(q, data, results, hidden, saved, app.csrf, bool(app.operator_pin), edit if edit in ids else None, ran, errors)


def post(app, parts: list[str], f: dict) -> tuple[str | None, list[str] | None]:
    """-> (redirect location, None) on success or (None, errors). parts: ['market','save'] | ['market',cid,'edit'|'pause'|'resume']."""
    try:
        if parts == ["market", "save"]:
            msg = app.wanted_change(mv.save_form(f), None, "create")
        elif len(parts) == 3 and parts[2] in ("edit", "pause", "resume"):
            msg = app.wanted_change(mv.save_form(f) if parts[2] == "edit" else f, parts[1], parts[2])
        else:
            raise InputError("unknown marketplace action")
    except InputError as ex:
        return None, [str(ex)]
    return f"/market?msg={quote(msg)}", None
