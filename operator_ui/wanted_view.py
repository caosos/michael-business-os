"""F-23: the "Wanted" page. Standing demand (`mbos.campaign`, A-26) that Michael creates, pauses or cancels, plus the matches 02's
matcher (`mbos_discovery.campaigns.match_campaign`, B-20) finds over the CURRENT Items, each with its plain-English why.

Only WATCH_ONLY and RECOMMEND may be created or run. ASSISTED_DEAL and BOUNDED_AUTOPILOT are shown but disabled, with the reason
from Agent 05's campaign policy (E-17, `decide_campaign`); a create attempt at those levels is refused server-side with that
reason and stores nothing. A campaign authorises nothing and the page contacts nobody: it reads Items and recommends.
Storage is a local JSON file (`MBOS_CAMPAIGNS_FILE`): the spine has no campaign table yet (UNKNOWN; proposed to lane A/D).
Human channel only (R14): CSRF + PIN, the author is set by the server."""

from __future__ import annotations

import html
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any, Optional

from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
LEVELS = ("WATCH_ONLY", "RECOMMEND", "ASSISTED_DEAL", "BOUNDED_AUTOPILOT")
RUNNABLE = ("WATCH_ONLY", "RECOMMEND")
OPEN_STATES = ("DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL", "HELD")
MAX_WORDS, MAX_TITLE = 12, 200
FALLBACK_REASONS = {"ASSISTED_DEAL": "ASSISTED_DEAL_NEEDS_STEP_UP: not available on this page; it can only draft through the approval path",
                    "BOUNDED_AUTOPILOT": "AUTOPILOT_NOT_AUTHORIZED"}
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


# ---------------------------------------------------------------- policy (E-17)
def level_reasons(policy_path: Optional[str] = None) -> dict:
    """{level: reason} for the levels this page will not run, from 05's `decide_campaign` over a probe campaign. Fail closed: with no
    policy or no governance package the fixed fallback text is used and the levels stay disabled."""
    out = dict(FALLBACK_REASONS)
    p = policy_path or os.environ.get("MBOS_POLICY_PATH")
    try:
        from mbos_governance.campaigns import decide_campaign
        from mbos_governance.policy import load_policy

        pol = load_policy(p)
        for lvl in FALLBACK_REASONS:
            d = decide_campaign(probe(lvl), pol)
            if d.decision == "deny" and d.reasons and "CAMPAIGN_INVALID" not in d.reasons:
                out[lvl] = ", ".join(d.reasons)
            elif d.decision == "require_approval":
                out[lvl] = "ASSISTED_DEAL only drafts, through tier 0 + step-up + your YES; this page does not run it"
    except Exception:  # noqa: BLE001 - fail closed to the fixed text
        pass
    return out


def probe(level: str) -> dict:
    doc = {"campaign_version": "1.0.0", "campaign_id": new_id(), "owner": "michael", "title": "probe",
           "criteria": {"category": "trailer", "keywords": [], "max_price_usd": 1, "radius_miles": None, "origin": None,
                        "must_have": [], "nice_to_have": [], "cosmetics_matter": False},
           "autonomy": {"level": level}, "stop_conditions": {"fulfilled_by": None, "expires_at": None, "max_matches": None},
           "status": "ACTIVE"}
    if level == "BOUNDED_AUTOPILOT":
        doc["autonomy"]["limits"] = {"max_offer_usd": 1, "max_total_spend_usd": 1, "expires_at": "2099-01-01T00:00:00Z"}
    return doc


def new_id() -> str:
    return "cmp_" + "".join(_CROCKFORD[b % 32] for b in secrets.token_bytes(26))


# ---------------------------------------------------------------- store
class CampaignStore:
    """A JSON file {"campaigns": {id: {"doc", "history"}}}, written atomically. Every change appends a history row (who, when, what)."""

    def __init__(self, path: Optional[str]):
        self.path = path

    def _read(self) -> dict:
        if not self.path:
            raise InputError("MBOS_CAMPAIGNS_FILE is not set: campaigns cannot be saved")
        try:
            return json.loads(Path(self.path).read_text("utf-8"))
        except FileNotFoundError:
            return {"campaigns": {}}
        except (OSError, ValueError):
            raise InputError("the campaigns file is unreadable; fix or remove it") from None

    def all(self) -> list[dict]:
        try:
            return list(self._read()["campaigns"].values())
        except (InputError, KeyError, AttributeError):
            return []

    def put(self, doc: dict, by: str, what: str, now: str) -> None:
        data = self._read()
        rec = data["campaigns"].setdefault(doc["campaign_id"], {"doc": doc, "history": []})
        rec["doc"] = doc
        rec["history"].append({"at": now, "by": by, "what": what})
        d = Path(self.path).parent
        d.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".campaigns-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def get(self, cid: str) -> Optional[dict]:
        return next((r for r in self.all() if r["doc"]["campaign_id"] == cid), None)


# ---------------------------------------------------------------- parsing
def _words(raw: str, label: str) -> list[str]:
    ws = [w.strip() for w in re.split(r"[,\n]", raw or "") if w.strip()]
    if len(ws) > MAX_WORDS or any(len(w) > 60 for w in ws):
        raise InputError(f"{label}: at most {MAX_WORDS} short words, separated by commas")
    return ws


def parse_campaign(f: dict, owner: str, reasons: dict, existing: Optional[dict] = None) -> dict:
    """Form -> a campaign document. A level above RECOMMEND is refused here with the policy reason (nothing is built).
    F-97: with `existing` (an edit) the id, owner, status and stop conditions are kept and only the criteria and level change."""
    from . import numbers_view

    level = f.get("level") or "RECOMMEND"
    if level not in LEVELS:
        raise InputError("unknown autonomy level; refused (fail closed)")
    if level not in RUNNABLE:
        raise InputError(f"{level} is refused: {reasons.get(level) or FALLBACK_REASONS[level]}")
    title = (f.get("title") or "").strip()
    if not title or len(title) > MAX_TITLE:
        raise InputError(f"Title is required (at most {MAX_TITLE} characters)")
    cat = (f.get("category") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_ -]{1,40}", cat):
        raise InputError("Category is required (letters and numbers, like trailer)")
    price = numbers_view.parse_amount(f.get("max_price_usd"), "Max price", cap=numbers_view.MAX_USD, required=True)
    radius = numbers_view.parse_amount(f.get("radius_miles"), "Radius (miles)", cap=numbers_view.Decimal("3000"), required=False)
    origin = (f.get("origin") or "").strip() or None
    if origin and len(origin) > 80:
        raise InputError("Origin is limited to 80 characters")
    keep = existing or {}
    return {"campaign_version": "1.0.0", "campaign_id": keep.get("campaign_id") or new_id(), "owner": keep.get("owner") or owner, "title": title,
            "criteria": {"category": cat, "keywords": _words(f.get("keywords"), "Keywords"), "max_price_usd": float(price),
                         "radius_miles": None if radius is None else float(radius), "origin": origin,
                         "must_have": _words(f.get("must_have"), "Must have"), "nice_to_have": _words(f.get("nice_to_have"), "Nice to have"),
                         "cosmetics_matter": f.get("cosmetics_matter") == "on"},
            "autonomy": {"level": level},
            "stop_conditions": keep.get("stop_conditions") or {"fulfilled_by": None, "expires_at": None, "max_matches": None},
            "status": keep.get("status") or "ACTIVE"}


# ---------------------------------------------------------------- matches
def matches_for(doc: dict, items: list[dict], now) -> dict:
    """02's matcher over the given Items. A refused campaign (paused, cancelled, above RECOMMEND) returns its reason and no matches."""
    try:
        from mbos_discovery.campaigns import match_campaign
    except ImportError:
        return {"refused": "the matcher (mbos_discovery, lane 02) is not installed", "matches": []}
    try:
        return match_campaign(doc, items, now)
    except Exception as ex:  # noqa: BLE001 - one bad Item must not take the page down
        return {"refused": f"the matcher failed: {type(ex).__name__}", "matches": []}


# ---------------------------------------------------------------- rendering
def _match_row(m: dict, titles: dict) -> str:
    return (f"<li><b><a href='/item/{e(m['item_id'])}'>{e(titles.get(m['item_id']) or m['item_id'])}</a></b> "
            f"<span class='mut small'>rank {e(m['rank'])} · {('$%g' % m['price']) if m.get('price') is not None else 'price UNKNOWN'} · "
            f"{e(m['distance']['note'])}</span><br><span class='small'>{e(m['why'])}</span></li>")


def render_page(records: list[dict], items: list[dict], now, csrf: str, pin_set: bool, reasons: dict, errors=None, values=None) -> str:
    values = values or {}
    titles = {i["item_id"]: ((i.get("normalized") or {}).get("title") or (i.get("title"))) for i in items}
    tok = lambda: f"<input type='hidden' name='csrf' value='{e(csrf)}'><input type='hidden' name='nonce' value='{secrets.token_hex(8)}'>"  # noqa: E731
    pin = "<input type='password' name='pin' placeholder='PIN' autocomplete='off' required>" if pin_set else "<span class='bad'>PIN not set: changes refused</span>"
    err = (f"<div class='flash err'><b>Not saved.</b><ul>{''.join(f'<li>{e(r)}</li>' for r in errors)}</ul></div>" if errors else "")
    opts = "".join(
        f"<option value='{l}'{' selected' if (values.get('level') or 'RECOMMEND') == l else ''}{'' if l in RUNNABLE else ' disabled'}>"
        f"{l}{'' if l in RUNNABLE else ' (disabled: ' + e(reasons.get(l) or FALLBACK_REASONS[l]) + ')'}</option>" for l in LEVELS)
    v = lambda k, d="": e(values.get(k, d))  # noqa: E731
    form = (f"<div class='card'><h2>New wanted campaign</h2><form method='post' action='/wanted/create'>{tok()}"
            f"<label>Title <input name='title' size='50' maxlength='{MAX_TITLE}' value='{v('title')}' required></label><br>"
            f"<label>Category <input name='category' size='12' value='{v('category')}' required></label> "
            f"<label>Keywords <input name='keywords' size='24' placeholder='5x8, utility' value='{v('keywords')}'></label> "
            f"<label>Max price (USD) <input name='max_price_usd' size='8' inputmode='decimal' value='{v('max_price_usd')}' required></label> "
            f"<label>Radius (miles) <input name='radius_miles' size='6' inputmode='decimal' value='{v('radius_miles')}'></label><br>"
            f"<label>Must have <input name='must_have' size='24' value='{v('must_have')}'></label> "
            f"<label>Nice to have <input name='nice_to_have' size='24' placeholder='title' value='{v('nice_to_have')}'></label> "
            f"<label><input type='checkbox' name='cosmetics_matter'{' checked' if values.get('cosmetics_matter') else ''}> cosmetics matter</label><br>"
            f"<label>Autonomy <select name='level'>{opts}</select></label> {pin} <button>Create</button></form>"
            "<p class='small mut'>A campaign only watches and recommends. It never contacts a seller, bids or buys; every action still needs your YES. "
            "Origin blank = Conway.</p></div>")
    cards = []
    def _one(r):
        d, hist = r["doc"], r["history"]
        c = d["criteria"]
        active = d["status"] == "ACTIVE"
        res = matches_for(d, items, now) if active else {"refused": f"status {d['status']}: not running", "matches": []}
        if res.get("refused"):
            body = f"<p class='mut'>{e(res['refused'])}</p>"
        elif res["matches"]:
            body = f"<ul>{''.join(_match_row(m, titles) for m in res['matches'])}</ul>"
        else:
            body = f"<p class='mut'>No current Item matches ({res.get('evaluated', 0)} checked). Recommendation only; nothing was contacted. <b>No source is hunting for this yet</b>: this list only filters Items already in the store.</p>"
        btn = lambda act, label: (f"<form method='post' action='/wanted/{e(d['campaign_id'])}/{act}' style='display:inline'>{tok()}{pin} <button>{label}</button></form>")  # noqa: E731
        ctl = (btn("pause", "Pause") if active else btn("resume", "Resume") if d["status"] == "PAUSED" else "") + \
              (btn("cancel", "Cancel") if d["status"] in ("ACTIVE", "PAUSED") else "")
        spec = (f"{e(c['category'])} · max ${c['max_price_usd']:g}" + (f" · {c['radius_miles']:g} mi" if c.get("radius_miles") is not None else "") +
                (f" · keywords {e(', '.join(c['keywords']))}" if c.get("keywords") else "") +
                f"<br>must have: {e(', '.join(c.get('must_have') or []) or 'none')} · nice to have: {e(', '.join(c.get('nice_to_have') or []) or 'none')}" +
                f" · cosmetics {'matter' if c.get('cosmetics_matter') else 'ignored'}")
        edit = ""
        if d["status"] in ("ACTIVE", "PAUSED"):  # F-97: an edit is a new revision of the same campaign; status and stop conditions are kept
            ev = lambda k: e(", ".join(c.get(k) or []))  # noqa: E731
            lvl = "".join(f"<option value='{l}'{' selected' if d['autonomy']['level'] == l else ''}{'' if l in RUNNABLE else ' disabled'}>{l}</option>" for l in LEVELS)
            edit = (f"<details><summary>Edit</summary><form method='post' action='/wanted/{e(d['campaign_id'])}/edit'>{tok()}"
                    f"<label>Title <input name='title' size='50' maxlength='{MAX_TITLE}' value='{e(d['title'])}' required></label><br>"
                    f"<label>Category <input name='category' size='12' value='{e(c['category'])}' required></label> "
                    f"<label>Keywords <input name='keywords' size='24' value='{ev('keywords')}'></label> "
                    f"<label>Max price (USD) <input name='max_price_usd' size='8' inputmode='decimal' value='{e(c['max_price_usd'])}' required></label> "
                    f"<label>Radius (miles) <input name='radius_miles' size='6' inputmode='decimal' value='{e('' if c.get('radius_miles') is None else c['radius_miles'])}'></label><br>"
                    f"<label>Must have <input name='must_have' size='24' value='{ev('must_have')}'></label> "
                    f"<label>Nice to have <input name='nice_to_have' size='24' value='{ev('nice_to_have')}'></label> "
                    f"<label><input type='checkbox' name='cosmetics_matter'{' checked' if c.get('cosmetics_matter') else ''}> cosmetics matter</label><br>"
                    f"<input type='hidden' name='origin' value='{e(c.get('origin') or '')}'>"
                    f"<label>Autonomy <select name='level'>{lvl}</select></label> {pin} <button>Save changes</button></form></details>")
        last = hist[-1] if hist else {}
        return (f"<div class='card'><div class='row'><b class='grow'>{e(d['title'])}</b><span class='badge'>{e(d['status'])}</span>"
                     f"<span class='badge'>{e(d['autonomy']['level'])}</span></div><p class='small mut'>{spec}<br>"
                     f"last change: {e(last.get('what'))} by {e(last.get('by'))} at {e(last.get('at'))}</p>{body}{ctl}{edit}</div>")

    for r in records:  # F-82: one malformed stored campaign is one error row, never a broken page
        try:
            cards.append(_one(r))
        except Exception as ex:  # noqa: BLE001
            cid = r["doc"].get("campaign_id") if isinstance(r, dict) and isinstance(r.get("doc"), dict) else None
            cards.append(f"<div class='card'><p class='bad'><b>Campaign {e(cid or '(unknown id)')} cannot be shown</b>: its stored record is "
                         f"malformed ({e(type(ex).__name__)}). Other campaigns are unaffected.</p></div>")
    head = "<h1>Wanted</h1>" + (f"<p class='mut'>{len(items)} current Items checked. Dry-run: nothing is contacted.</p>")
    return err + head + form + ("".join(cards) or "<p class='mut'>No campaigns yet.</p>")
