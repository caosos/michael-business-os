"""F-19: DRAFT audience-view previews of an inventory object. Read-only except "check my wording", which only LINTS.

Never publishes. The inventory comes from a local file (`MBOS_INVENTORY_FILE`): no spine store for inventory exists yet.
Every preview is labelled DRY-RUN. A view that fails `mbos.merchandising.lint` is shown as REFUSED with the reasons, not as an ad.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Optional

from . import merch

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def load_inventory(path: Optional[str] = None) -> dict:
    """{'doc', 'errors', 'path'}; never raises."""
    p = path or os.environ.get("MBOS_INVENTORY_FILE")
    if not p:
        return {"doc": None, "errors": ["MBOS_INVENTORY_FILE is not set: no inventory object to preview"], "path": None}
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"doc": None, "errors": ["inventory file not found"], "path": p}
    except (OSError, ValueError) as ex:
        return {"doc": None, "errors": [f"unreadable inventory: {type(ex).__name__}"], "path": p}
    from mbos import merchandising

    return {"doc": doc, "errors": merchandising.inventory_errors(doc), "path": p}


def _facts(inv: dict) -> str:
    rows = "".join(f"<tr><td>{e(f['key'])}</td><td>{'<b class=unk>UNKNOWN</b>' if f['basis'] == 'UNKNOWN' else e(f['value'])}</td>"
                   f"<td><span class='tag {'fact' if f['basis'] == 'verified' else 'inf'}'>{e(f['basis'])}</span></td>"
                   f"<td>{'material' if f.get('material') else ''}</td></tr>" for f in inv["facts"])
    defects = "".join(f"<li><b>{e(d['severity'])}</b>: {e(d['text'])} <span class='tag inf'>{e(d['basis'])}</span></li>" for d in inv["defects"])
    return (f"<div class='card'><h2>Inventory facts (the single source of truth)</h2><table><tr><th>Fact</th><th>Value</th><th>Basis</th><th></th></tr>{rows}</table>"
            f"<h2 style='margin-top:10px'>Defects (disclosed verbatim in every view)</h2><ul>{defects or '<li class=mut>none listed</li>'}</ul>"
            f"<p class='small mut'>Terms: {e(merch._terms_line(inv['terms']))} (the same in every view)</p></div>")


def _view_card(inv: dict, audience: str, csrf: str, result: Optional[dict] = None) -> str:
    """One audience: the deterministic draft (always lint-clean) plus a 'check my wording' form for edits."""
    try:
        v = merch.render_view(inv, audience)
        refusal = None
    except merch.MerchRefused as ex:
        v, refusal = None, ex.reasons
    if refusal:
        return (f"<div class='card'><h2>{e(merch.LABELS[audience])}</h2><div class='flash err'><b>REFUSED: this view would not be truthful.</b><ul>"
                + "".join(f"<li>{e(r)}</li>" for r in refusal) + "</ul></div></div>")
    edited = result if (result and result["audience"] == audience) else None
    headline, body, cta = (edited["headline"], edited["body"], edited["call_to_action"]) if edited else (v["headline"], v["body"], v["call_to_action"])
    boxes = "".join(f"<label><input type='checkbox' name='disclose' value='{e(d['id'])}'{' checked' if not (edited and d['id'] in edited['dropped']) else ''}>"
                    f"Include the disclosure: {e(d['text'])}</label><br>" for d in inv["defects"])
    verdict = ""
    if edited:
        verdict = ("<div class='flash err'><b>REFUSED: your wording is not a truthful presentation.</b><ul>" + "".join(f"<li>{e(r)}</li>" for r in edited["reasons"]) + "</ul></div>"
                   if edited["reasons"] else "<div class='flash'><b class='ok'>Passes the truthfulness lint.</b> Still a draft: nothing is published.</div>")
    return (f"<div class='card'><div class='row'><h2>{e(v['label'])}</h2><span class='tag rec'>DRY-RUN draft: nothing is published</span>"
            f"<span class='grow'></span><span class='tag fact'>passes lint</span></div>{verdict}"
            f"<h1>{e(headline)}</h1><p>{e(body)}</p><p><b>{e(cta)}</b></p>"
            f"<details><summary>Check my own wording</summary><form method='post' action='/preview/check'><input type='hidden' name='csrf' value='{e(csrf)}'>"
            f"<input type='hidden' name='audience' value='{e(audience)}'><label>Headline<input name='headline' value='{e(headline)}' maxlength='200'></label>"
            f"<label>Body<textarea name='body'>{e(body)}</textarea></label><label>Call to action<input name='call_to_action' value='{e(cta)}' maxlength='200'></label>"
            f"{boxes}<p class='small mut'>Terms cannot be changed per audience. This only checks; it never publishes.</p>"
            "<button class='b-HOLD' style='width:auto'>Check</button></form></details></div>")


def render_page(loaded: dict, csrf: str, result: Optional[dict] = None) -> str:
    head = ("<div class='card'><h2>Audience previews</h2><p class='small mut'>Deterministic templates (no AI), built only from the inventory facts below. "
            "Every view is a <b>DRY-RUN draft</b>: publishing would be a separate request that needs your approval. Photos shown are the "
            "current photos only; there is no generated \"finished look\" here.</p></div>")
    if loaded["doc"] is None:
        return head + f"<div class='card'><p class='bad'>{e('; '.join(loaded['errors']))}</p></div>"
    if loaded["errors"]:
        return (head + "<div class='flash err'><b>This inventory is not valid, so no preview is made.</b><ul>"
                + "".join(f"<li>{e(x)}</li>" for x in loaded["errors"][:10]) + "</ul></div>")
    inv = loaded["doc"]
    return (head + f"<div class='card'><h1>{e(inv['title'])}</h1><span class='small mut'>{e(inv['category'])} · {e(inv['inventory_id'])}</span></div>"
            + _facts(inv) + "".join(_view_card(inv, a, csrf, result) for a in merch.AUDIENCES))
