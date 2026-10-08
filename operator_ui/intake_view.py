"""F-20: conversational-intake front door. A deterministic (no LLM) draft flow over `mbos.intake` (A-27).

"sell this mower, smokes, at least $400" -> a draft, what the seller already said (recorded `seller_stated`), and only the questions
still missing (safety and material first). Nothing here can mark a fact `verified` (intake refuses it), publish, contact or spend.
"""

from __future__ import annotations

import html
import re
import secrets
from typing import Optional

from mbos import intake

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

KEYWORDS = {"mower": ("mower", "lawnmower", "zero turn", "zero-turn"), "trailer": ("trailer",),
            "home_repair_job": ("repair", "fix my", "install", "handyman", "smart home", "leak")}
_PRICE = re.compile(r"(at least|min(?:imum)?|no less than|asking|for)?\s*\$\s?(\d[\d,]*(?:\.\d\d)?)", re.I)
_DEFECT_WORDS = ("smoke", "smokes", "smoking", "leaks", "leaking", "won't start", "doesn't start", "knocks", "broken", "cracked", "rust", "rusty")


def detect_spec(text: str) -> Optional[str]:
    low = text.lower()
    for name, words in KEYWORDS.items():
        if name in intake.available() and any(w in low for w in words):
            return name
    return None


def start(text: str) -> dict:
    """Draft from one sentence. Everything extracted is `seller_stated` (the seller's own words), never verified."""
    spec = detect_spec(text)
    if spec is None:
        raise ValueError("I could not tell what this is (try: mower, trailer, or a repair job)")
    d = intake.new_draft(spec)
    keys = {f["key"] for f in intake.load_spec(spec)["fields"]}
    m = _PRICE.search(text)
    if m and "price_usd" in keys:
        floor = bool(m.group(1) and m.group(1).lower() in ("at least", "min", "minimum", "no less than"))
        d = intake.answer(d, "price_usd", f"{'at least ' if floor else ''}${m.group(2)}", "seller_stated")
    defects = [w for w in re.split(r"[,;]", text.lower()) if any(x in w for x in _DEFECT_WORDS)]
    if defects and "known_defects" in keys:
        d = intake.answer(d, "known_defects", "; ".join(x.strip() for x in defects), "seller_stated")
    d["source_text"] = text
    return d


def inventory_draft(d: dict) -> dict:
    """Facts for the inventory object, basis carried unchanged. A DRAFT: not published, not validated as an inventory object."""
    facts = intake.to_inventory_facts(d)
    return {"status": "DRAFT", "dry_run": True, "published": False, "kind": d["kind"], "category": d["category"], "facts": facts,
            "defects": [{"text": str(f["value"]), "basis": f["basis"]} for f in facts if f["key"] == "known_defects" and f["basis"] != "UNKNOWN"],
            "unverified_facts": [f["key"] for f in facts if f["basis"] != "verified"]}


def apply_answers(d: dict, form: dict) -> dict:
    """Record submitted answers: `a_<key>` text, `u_<key>` = the seller does not know. Blank is ignored; unknown keys raise."""
    for k, v in form.items():
        if k.startswith("u_") and v:
            d = intake.answer(d, k[2:], None, "UNKNOWN")
        elif k.startswith("a_") and v.strip() and f"u_{k[2:]}" not in form:
            key = k[2:]
            if key.startswith("photo:"):
                d = dict(d, evidence=d["evidence"] + [{"kind": "photo", "ref": v.strip()}])  # a photo reference, still unverified
            else:
                d = intake.answer(d, key, v.strip(), "seller_stated")
    return d


def new_id() -> str:
    return "int-" + secrets.token_hex(4)


def render_start(csrf: str, flash: str = "") -> str:
    return (f"{flash}<div class='card'><h2>Intake (DRY-RUN draft)</h2><p class='small mut'>Say what you want to sell or get done. Nothing is published, "
            f"sent or marked verified.</p><form method='post' action='/intake/start'><input type='hidden' name='csrf' value='{e(csrf)}'>"
            "<input name='text' size='70' placeholder='sell this mower, smokes, at least $400' required> <button>Start draft</button></form></div>")


def render_draft(iid: str, d: dict, csrf: str) -> str:
    qs = intake.missing(d)
    got = "".join(f"<tr><td>{e(k)}</td><td>{'<b class=unk>UNKNOWN</b>' if a['basis'] == 'UNKNOWN' else e(a['value'])}</td>"
                  f"<td><span class='tag inf'>{e(a['basis'])}</span></td></tr>" for k, a in d["answers"].items())
    rows = "".join(f"<tr><td>{'<b>SAFETY</b> ' if q['safety_relevant'] else ''}{'material' if q['material'] else ''}</td><td>{e(q['ask'])}</td>"
                   f"<td><input name='a_{e(q['key'])}'> <label><input type='checkbox' name='u_{e(q['key'])}' value='1'>I don't know</label></td></tr>" for q in qs)
    form = (f"<form method='post' action='/intake/{e(iid)}/answer'><input type='hidden' name='csrf' value='{e(csrf)}'>"
            f"<table><tr><th></th><th>Still needed ({len(qs)}, safety first)</th><th>Answer</th></tr>{rows}</table><button>Record answers</button></form>") if qs else "<p>Nothing missing.</p>"
    inv = inventory_draft(d)
    return (f"<div class='card'><h2>Draft {e(d['category'])} <span class='tag inf'>DRAFT</span> <span class='tag inf'>DRY-RUN</span></h2>"
            f"<p class='small mut'>You said: {e(d.get('source_text', ''))}. Not published. Verified facts: 0. Unverified: {len(inv['unverified_facts'])}.</p>"
            f"<table><tr><th>Fact</th><th>Value</th><th>Basis</th></tr>{got or '<tr><td colspan=3 class=mut>nothing yet</td></tr>'}</table></div>"
            f"<div class='card'>{form}</div>")
