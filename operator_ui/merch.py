"""F-19: deterministic audience views of an inventory object (templates, NO LLM), previewed as DRAFTS in the UI.

`render_view(inventory, audience)` builds only from the inventory's own facts, defects and terms, and runs
`mbos.merchandising.lint` before returning. A view that would not pass is REFUSED (MerchRefused with the lint reasons),
never softened: defects are disclosed verbatim, terms are copied, fact bases are carried unchanged, and the word "verified"
appears only for facts that are verified. Nothing here publishes: publishing is a separate gated ActionRequest.

Current photos are never mixed with an AI "possible finished look": this module has no image or generation code at all.
"""

from __future__ import annotations

from typing import Any

from mbos import merchandising
from mbos.hashing import sha256_of

LABELS = {"ordinary_classified": "Classified", "flipper": "Project / Fix & Flip", "mechanic": "Mechanic Special", "parts_buyer": "Parts / Donor"}
AUDIENCES = tuple(LABELS)
_BASIS_WORDS = {"seller_stated": "seller says", "system_inferred": "inferred", "verified": "verified", "UNKNOWN": "unknown"}


class MerchRefused(ValueError):
    """The view would not be a truthful presentation. `.reasons` are the lint reasons, shown verbatim."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def _price(t: dict) -> str:
    p = t["price_usd"]
    amt = f"${p:,.0f}" if float(p).is_integer() else f"${p:,.2f}"
    return {"fixed": amt, "obo": f"{amt} or best offer", "auction_start": f"Auction, starting at {amt}",
            "reserve": f"Reserve {amt}", "free": "Free"}[t["price_type"]]


def _terms_line(t: dict) -> str:
    bits = [_price(t)]
    if t.get("pickup"):
        bits.append(str(t["pickup"]))
    if t.get("delivery"):
        bits.append(str(t["delivery"]))
    return ". ".join(bits) + "."


def _fact_phrase(f: dict, with_basis: bool) -> str:
    val = "unknown" if f["basis"] == "UNKNOWN" else str(f["value"])
    key = f["key"].replace("_", " ")
    text = val if f["key"] == "make_model" else f"{key.capitalize()}: {val}"
    return text + (f" ({_BASIS_WORDS[f['basis']]})" if with_basis else "")


def _known(inv: dict) -> list[dict]:
    return [f for f in inv["facts"] if f["basis"] != "UNKNOWN"]


def _unknown_keys(inv: dict) -> list[str]:
    return [f["key"].replace("_", " ") for f in inv["facts"] if f["basis"] == "UNKNOWN"]


def _defect_sentences(inv: dict) -> str:
    return " ".join(f"{d['text'].rstrip('.')}." for d in inv["defects"])


def _status(inv: dict) -> str:
    f = next((x for x in inv["facts"] if x["key"] == "operating_status" and x["basis"] != "UNKNOWN"), None)
    return str(f["value"]) if f else ""


def _headline_body(inv: dict, audience: str) -> tuple[str, str, str]:
    title, status = inv["title"], _status(inv)
    known = [_fact_phrase(f, False) for f in _known(inv)]
    unk = _unknown_keys(inv)
    unk_s = f"Not known: {', '.join(unk)}." if unk else ""
    defects = _defect_sentences(inv)
    terms = _terms_line(inv["terms"])
    if audience == "ordinary_classified":
        return (f"{title}" + (f", {status}" if status else ""),
                " ".join(x for x in (f"{'. '.join(known)}." if known else "", defects, terms) if x), "Call or message.")
    if audience == "flipper":
        return (f"Fix-and-flip candidate: {title}",
                " ".join(x for x in (f"Seller asks: {_price(inv['terms'])}.", f"Known faults: {defects}" if defects else "No faults were listed by the seller.",
                                     unk_s, f"{'. '.join(known)}." if known else "") if x), "Make an offer.")
    if audience == "mechanic":
        return (f"Mechanic special: {title}" + (f", {status}" if status else ""),
                " ".join(x for x in (f"What is stated: {'; '.join(_fact_phrase(f, True) for f in inv['facts'] if f['basis'] != 'UNKNOWN')}." if known else "",
                                     f"Defects: {defects}" if defects else "", unk_s, terms) if x),
                "Message with questions or to arrange pickup.")
    if audience == "parts_buyer":
        return (f"{title} for parts or repair",
                " ".join(x for x in (f"{'. '.join(known)}." if known else "", defects, unk_s, "See the photos for what is shown.", terms) if x),
                "Ask about pickup.")
    raise MerchRefused([f"no template for audience {audience!r} (supported: {', '.join(AUDIENCES)})"])


def build_view(inv: dict, audience: str, *, headline=None, body=None, call_to_action=None, drop_disclosures=()) -> dict:
    """Assemble a view dict WITHOUT linting. `render_view` lints it; the UI's "check my wording" passes edited text and may
    leave a disclosure out to show that the lint refuses it."""
    h, b, c = _headline_body(inv, audience)
    return {
        "view_version": "1.0.0", "inventory_id": inv["inventory_id"], "inventory_hash": sha256_of(inv), "audience": audience,
        "label": LABELS.get(audience, audience), "headline": h if headline is None else headline, "body": b if body is None else body,
        "facts": [{"fact_id": f["id"], "basis": f["basis"], **({"provenance_id": f["provenance_id"]} if f.get("provenance_id") else {})}
                  for f in inv["facts"]],
        "disclosures": [{"defect_id": d["id"], "text": d["text"]} for d in inv["defects"] if d["id"] not in set(drop_disclosures)],
        "terms": dict(inv["terms"]), "call_to_action": c if call_to_action is None else call_to_action,
    }


def render_view(inv: dict, audience: str) -> dict:
    errs = merchandising.inventory_errors(inv)
    if errs:
        raise MerchRefused([f"inventory is not valid: {x}" for x in errs])
    view = build_view(inv, audience)
    reasons = merchandising.lint(inv, view)
    if reasons:  # never emit, never soften
        raise MerchRefused(reasons)
    return view


def check_view(inv: dict, view: dict) -> list[str]:
    """Lint reasons for ANY view (empty = truthful). Used for Michael's own edits."""
    return merchandising.lint(inv, view)
