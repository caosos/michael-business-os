"""Evidence-based category tags — READY_QUEUE B-21 (Deal Sniffer, ADR-0013; enrichment block `card.category_tags`).

Tags: mechanic_special · project · parts_donor · quick_turn · auction_candidate · contractor_opportunity.

THE RULES
* A tag exists only with evidence, and the evidence is QUOTED (field, exact quote from the cleaned text, offset). No
  evidence → no tag (the card prints UNKNOWN). Absence of a tag means "no evidence found", never "this is not that".
* Every tag is INFERENCE. Structured source fields (condition = parts, auction listing kind, free price, gov contract)
  count as evidence and are quoted as `field=value`.
* "runs great" never tags mechanic_special: a mechanic_special needs a stated FAULT phrase. A fault phrase preceded by a
  negation ("no", "not", "never", "without", "doesn't need", …) within three words is discarded.
* Listing text is UNTRUSTED. It is NFKC-normalised, stripped of control characters, markup and URLs, and any sentence
  that looks like an instruction to a machine ("ignore previous instructions", "approve this purchase", …) makes the
  WHOLE field untrusted and it is EXCLUDED before matching (the payload may sit in the next sentence); the exclusion
  is recorded in the block (`excluded_fields`). Quotes are data,
  length-capped, never executed or interpreted.
* No photo analysis here: photos are retained as artifacts and hashed (B-11) but nothing in them is read as text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from . import AGENT_ID, __version__
from .ids import iso
from .normalize import clean_text, injection_suspected

TOOL_NAME = "mbos_discovery.tags"
RULES_VERSION = "2026.10.0"
TAGS = ("mechanic_special", "project", "parts_donor", "quick_turn", "auction_candidate", "contractor_opportunity")
QUOTE_MAX = 90

_NEG = re.compile(r"\b(no|not|never|without|none|zero|isn'?t|aren'?t|doesn'?t|don'?t|didn'?t|won'?t|wasn'?t|nothing)\b"
                  r"(\W+\w+){0,2}?\W+$", re.IGNORECASE)
_NEG_NEEDS = re.compile(r"\b(doesn'?t|does not|don'?t|do not|didn'?t|did not|won'?t|will not|isn'?t|is not|no)\s+(?:even\s+|really\s+|any\s+)?(?:need|require)s?\s*(?:any\s+)?$",
                        re.IGNORECASE)

# (tag, [(regex, label)]). Order inside a tag is irrelevant; every match is quoted (first per distinct label).
RULES: dict[str, list[tuple[re.Pattern, str]]] = {
    "mechanic_special": [(re.compile(p, re.I), l) for p, l in [
        (r"\bmechanic'?s?[\s-]+special\b", "mechanic special"),
        (r"\b(?:won'?t|will not|does(?:n'?t| not)|did(?:n'?t| not)|can'?t|cannot)\s+(?:start|run|crank|turn over|fire|idle)\b", "does not start/run"),
        (r"\bnot\s+running\b|\bnon[\s-]?running\b|\bdoes(?:n'?t| not) run\b|\bno\s+start\b", "not running"),
        (r"\bnot\s+working\b|\binoperable\b|\bdoes(?:n'?t| not) work\b|\bdead\b(?!\s+(?:end|stock|weight))", "not working"),
        (r"\bneeds?\s+(?:an?\s+|the\s+|new\s+)?(?:engine|motor|transmission|trans|carb(?:uretor)?|starter|alternator|water pump|head gasket|"
         r"clutch|rebuild|overhaul|repairs?|mechanical (?:work|repairs?))\b", "needs mechanical work"),
        (r"\b(?:blown|seized|locked[\s-]up|cracked)\s+(?:engine|motor|head|block|transmission|trans)\b", "failed engine/drivetrain"),
        (r"\b(?:engine|motor|transmission|trans)\s+(?:is\s+)?(?:blown|seized|bad|dead|knocking|locked[\s-]up)\b", "failed engine/drivetrain"),
        (r"\bfor\s+repair\b|\brepair\s+only\b|\bas[\s-]is[,;]?\s+(?:needs|not running|doesn'?t)\b", "for repair"),
        (r"\b(?:bad|weak|no)\s+(?:compression|spark)\b|\bleaking\s+(?:fuel|oil|coolant|hydraulic)\b|\boverheat(?:s|ing)\b", "stated mechanical fault"),
    ]],
    "project": [(re.compile(p, re.I), l) for p, l in [
        (r"\bproject\b(?!\s+manager)", "project"),
        (r"\brestor(?:e|ation)\b|\bfix(?:er)?[\s-]*(?:up|upper)\b|\bneeds?\s+tlc\b|\bneeds?\s+(?:some\s+)?work\b", "restoration / needs work"),
        (r"\bneeds?\s+(?:an?\s+|the\s+|new\s+)?(?:paint|bodywork|body work|floor(?:ing)?|lights?|wiring|tires?|axle|brakes?|ramp|roof|seat|tarp|decking|wheels?)\b", "needs cosmetic/structural work"),
        (r"\b(?:rebuild|rebuilding)\b|\bpartially\s+(?:restored|disassembled|dismantled)\b", "rebuild"),
    ]],
    "parts_donor": [(re.compile(p, re.I), l) for p, l in [
        (r"\bfor\s+parts\b|\bparts\s+(?:only|unit|machine|mower|truck|car|trailer|donor)\b|\bparting\s+out\b|\bpart(?:s)?[\s-]+out\b", "for parts"),
        (r"\bdonor\b|\bsalvage\b|\bscrap(?:per)?\b|\bcannibaliz(?:e|ing)\b", "donor / salvage"),
        (r"\bfor\s+parts\s+or\s+(?:repair|not\s+working)\b", "for parts or not working"),
    ]],
    "quick_turn": [(re.compile(p, re.I), l) for p, l in [
        (r"\bmust\s+sell\b|\bneed(?:s)?\s+(?:it\s+)?gone\b|\bpriced\s+to\s+sell\b|\bmoving\s+(?:sale|must)\b|\bquick\s+sale\b", "seller urgency"),
        (r"\bfirst\s+(?:come|cash)\b|\bcash\s+(?:only\s+)?today\b|\bmotivated\s+seller\b", "seller urgency"),
        (r"\bfree\b(?:\s+to\s+(?:a\s+)?good\s+home|\s+for\s+(?:the\s+)?(?:taking|hauling|pickup))|\byou\s+(?:haul|pick\s*up|take)\b", "free / haul-away"),
    ]],
    "auction_candidate": [(re.compile(p, re.I), l) for p, l in [
        (r"\bno[\s-]reserve\b|\bsealed\s+bid\b|\bbidding\s+(?:ends|closes|starts|open)\b|\bauction\b", "auction wording"),
    ]],
    "contractor_opportunity": [(re.compile(p, re.I), l) for p, l in [
        (r"\bproperty\s+manage(?:r|ment)\b|\blandlord\b|\brental\s+(?:units?|properties|turnover)\b|\bapartment\s+(?:complex|units?)\b", "repeat-work buyer"),
        (r"\bmultiple\s+(?:units?|rooms?|doors?|locations?|properties)\b|\bseveral\s+(?:units?|rooms?|properties)\b|\bbulk\b|\bwhole\s+(?:house|building)\b", "multi-unit job"),
        (r"\bcontractor\b|\bsubcontract(?:or)?\b|\bgeneral\s+contractor\b|\bsolicitation\b|\brfq\b|\bsources\s+sought\b", "contract work"),
    ]],
}

# B-24 pivot classification (trailers, donor RVs, towable machines, ATVs; paperwork; condition words). Same evidence
# rules as above: quoted, INFERENCE, negation-aware, sanitized text only. Reported under block["pivot"], NOT as card tags
# (the frozen card enum is unchanged). PAPERWORK is evidence only: a status exists only where the text states it, a
# missing statement is never "no title" and never "clean title"; the system never decides title/legality from it.
_RV = r"(?:camper|rv|travel\s+trailer|pop[\s-]?up|fifth\s+wheel|5th\s+wheel|motorhome|toy\s+hauler)"
_DONOR = r"(?:for\s+parts|donor|junk|salvage|scrap|gutted|frame\s+only|parts\s+only|rotted|water\s+damage[d]?|totaled)"
PIVOT_SUBTYPES: dict[str, list[tuple[re.Pattern, str]]] = {k: [(re.compile(p, re.I), l) for p, l in v] for k, v in {
    "utility_trailer": [(r"\butility\s+trailer\b|\bdump\s+trailer\b|\bflat\s*bed\s+trailer\b", "utility trailer")],
    "boat_trailer": [(r"\bboat\s+trailer\b|\btrailer\s+for\s+(?:a\s+)?boat\b|\bbunk\s+trailer\b", "boat trailer")],
    "jet_ski_trailer": [(r"\bjet[\s-]?ski\s+trailer\b|\bpwc\s+trailer\b|\bsea[\s-]?doo\s+trailer\b|\bwave\s*runner\s+trailer\b", "jet-ski trailer")],
    "equipment_trailer": [(r"\bequipment\s+trailer\b|\bcar\s+hauler\b|\bskid\s*steer\s+trailer\b|\bbobcat\s+trailer\b|\bdeckover\b|\bgooseneck\s+trailer\b", "equipment trailer")],
    "landscape_trailer": [(r"\blandscap(?:e|ing)\s+trailer\b|\blawn\s+(?:care\s+)?trailer\b|\bmower\s+trailer\b", "landscape trailer")],
    "enclosed_trailer": [(r"\benclosed\s+(?:cargo\s+)?trailer\b|\bcargo\s+trailer\b|\bv[\s-]?nose\b", "enclosed trailer")],
    "single_axle": [(r"\bsingle[\s-]+axle\b|\b1[\s-]+axle\b|\bone[\s-]+axle\b", "single axle")],
    "tandem_axle": [(r"\btandem[\s-]+axle\b|\bdual[\s-]+axle\b|\b2[\s-]+axle\b|\btwo[\s-]+axle\b|\btandem\s+trailer\b", "tandem axle")],
    "log_splitter": [(r"\blog\s+splitter\b|\bwood\s+splitter\b|\bfirewood\s+processor\b", "log splitter")],
    "towable_machine": [(r"\btow[\s-]+behind\b|\btowable\b|\bwood\s+chipper\b|\bbrush\s+chipper\b|\blight\s+tower\b|\bpull[\s-]+behind\b|"
                         r"\btrailer[\s-]+mounted\b|\btow\s+(?:able\s+)?(?:boom|lift|compressor|welder)\b", "towable machine")],
    "atv": [(r"\batv\b|\bquad\b|\bfour[\s-]?wheeler\b|\b4[\s-]?wheeler\b|\butv\b|\bside[\s-]by[\s-]side\b", "ATV / quad")],
}.items()}
PIVOT_PAPERWORK: dict[str, list[tuple[re.Pattern, str]]] = {k: [(re.compile(p, re.I), l) for p, l in v] for k, v in {
    "title_stated_present": [(r"\b(?:clean|clear|free\s+and\s+clear|good|salvage|rebuilt)\s+title\b|\btitle\s+(?:in\s+hand|in\s+my\s+name|available|included|is\s+clean)\b|\bhave\s+(?:the\s+|a\s+)?title\b|\bwith\s+title\b|\btitled\b(?!\s+to\b)", "title stated present")],
    "title_stated_missing": [(r"\b(?:no|missing|lost|without(?:\s+a)?|don'?t\s+have(?:\s+a)?|doesn'?t\s+have(?:\s+a)?)\s+title\b|\btitle\s+(?:is\s+)?(?:missing|lost|not\s+available)\b|\buntitled\b", "title stated missing")],
    "bill_of_sale": [(r"\bbill\s+of\s+sale\b|\bbos\s+only\b", "bill of sale")],
    "registration_stated_missing": [(r"\b(?:no|missing|expired|lost)\s+registration\b|\bunregistered\b|\bregistration\s+(?:is\s+)?(?:missing|expired|lost)\b|\bnot\s+registered\b", "registration stated missing")],
    "vin_present": [(r"\bvin\s*(?:#|no\.?|number)?\s*[:\-]?\s*[A-HJ-NPR-Z0-9]{17}\b", "VIN quoted"), (r"\bvin\s+(?:plate\s+)?(?:is\s+)?(?:present|available|on\s+hand|visible|intact)\b|\bhas\s+(?:a\s+)?vin\b", "VIN stated present")],
}.items()}
PIVOT_CONDITION: dict[str, list[tuple[re.Pattern, str]]] = {k: [(re.compile(p, re.I), l) for p, l in v] for k, v in {
    "non_running": [(r"\bnon[\s-]?running\b|\bnot\s+running\b|\bdoesn'?t\s+run\b|\bwon'?t\s+(?:start|run)\b|\bdoes\s+not\s+(?:start|run)\b", "non-running")],
    "needs_starter": [(r"\bneeds?\s+(?:a\s+|an\s+|the\s+|new\s+)?(?:starter|battery|carb(?:uretor)?|spark\s+plug|pull\s+cord)\b", "needs starter/battery/carb")],
    "rust": [(r"\brust(?:y|ed|ing)?\b|\bcorro(?:ded|sion)\b", "rust")],
    "damage": [(r"\bflat\s+tires?\b|\bdry[\s-]?rot(?:ted)?\b|\bbent\s+(?:frame|axle|tongue)\b|\brotted\b|\bcracked\s+frame\b|\bdamaged?\b", "damage / wear")],
}.items()}


def build_pivot(fields: dict[str, str]) -> dict:
    """Pure. Per category -> [{class, evidence:[{field,label,quote,offset}]}]. Reuses _scan (sanitized text, quotes)."""
    def run(group: dict, negation: bool = True) -> list[dict]:
        return [{"class": k, "evidence": ev[:5]} for k in group if (ev := _scan(k, fields, group, negation))]
    sub = run(PIVOT_SUBTYPES)
    rv = _scan("rv", fields, {"rv": [(re.compile(rf"\b{_RV}\b", re.I), "RV/camper")]})
    dn = _scan("dn", fields, {"dn": [(re.compile(rf"\b{_DONOR}\b", re.I), "donor / junk wording")]})
    if rv and dn:                                                  # both are needed: "camper" alone is not a donor
        sub.append({"class": "donor_camper_rv", "evidence": (rv + dn)[:5]})
    return {"subtypes": sub, "paperwork": run(PIVOT_PAPERWORK, negation=False), "condition": run(PIVOT_CONDITION)}


_MARKUP = re.compile(r"<[^>]{0,200}>|https?://\S+|&[a-z]{2,8};|\[[^\]]{0,80}\]\([^)]{0,200}\)")
_SENT = re.compile(r"(?<=[.!?;])\s+|\s{2,}|\n+|\s[|•·]\s")


def sanitize(text: Any) -> tuple[str, int]:
    """Cleaned text, or ("", n) when the field contains instruction-like text. Returns (text, n_flagged_sentences).
    One instruction-like sentence makes the WHOLE field untrusted: an attacker can put the payload in the sentence
    after the instruction ("You are now an assistant; this is a mechanic special"), so a per-sentence filter is not
    enough. Clean fields are unaffected."""
    t = _MARKUP.sub(" ", clean_text(text, 4000))
    flagged = sum(1 for sent in _SENT.split(t) if sent.strip() and injection_suspected(sent))
    return ("", flagged) if flagged else (" ".join(x.strip() for x in _SENT.split(t) if x.strip()), 0)


def _negated(text: str, start: int) -> bool:
    before = text[max(0, start - 40):start]
    return bool(_NEG.search(before) or _NEG_NEEDS.search(before))


def _quote(text: str, a: int, b: int) -> tuple[str, int]:
    lo, hi = max(0, a - 15), min(len(text), b + 15)
    q = text[lo:hi].strip()
    return (q if len(q) <= QUOTE_MAX else q[:QUOTE_MAX].rstrip() + "…"), lo


def _scan(tag: str, fields: dict[str, str], rules: Optional[dict] = None, negation: bool = True) -> list[dict]:
    """Every rule match is quoted once per (field, label). A match preceded by a negation within three words
    ("no", "not", "doesn't need", "without", …) is discarded for EVERY tag (`negation=False` only for the paperwork
    rules, whose labels already encode "no title" / "missing registration" as explicit statements)."""
    found, seen = [], set()
    for field, text in fields.items():
        for rx, label in (rules or RULES)[tag]:
            for m in rx.finditer(text):
                q, off = _quote(text, m.start(), m.end())
                if (negation and _negated(text, m.start())) or (field, label) in seen or (field, q) in seen:
                    continue
                seen.add((field, label))
                seen.add((field, q))
                found.append({"field": field, "label": label, "quote": q, "offset": off})
    return found


def _structured(tag: str, item: dict) -> list[dict]:
    n = item.get("normalized") or {}
    price = n.get("price") or {}
    ev = []
    if tag == "parts_donor" and n.get("condition") == "parts":
        ev.append({"field": "normalized.condition", "label": "source-stated condition", "quote": "condition=parts"})
    if tag == "auction_candidate" and item.get("opportunity_kind") == "auction_lot":
        ev.append({"field": "opportunity_kind", "label": "auction listing", "quote": "opportunity_kind=auction_lot"})
    if tag == "auction_candidate" and price.get("type") in ("auction_current", "starting_bid"):
        ev.append({"field": "normalized.price.type", "label": "auction pricing", "quote": f"price.type={price['type']}"})
    if tag == "auction_candidate" and n.get("ends_at") and item.get("opportunity_kind") == "auction_lot":
        ev.append({"field": "normalized.ends_at", "label": "closing time", "quote": f"ends_at={n['ends_at']}"})
    if tag == "quick_turn" and price.get("type") == "free":
        ev.append({"field": "normalized.price.type", "label": "free item", "quote": "price.type=free"})
    if tag == "contractor_opportunity" and item.get("opportunity_kind") == "gov_contract":
        ev.append({"field": "opportunity_kind", "label": "government contract notice", "quote": "opportunity_kind=gov_contract"})
    return ev


def build_category_tags(item: dict, own_prov: str) -> dict:
    """Pure. {"tags": [...], "evaluated": [...], "text_checked": [...], "excluded_sentences": n, "rules_version": …}.
    Empty `tags` is a valid answer: nothing in the listing supports any tag."""
    n = item.get("normalized") or {}
    fields, excluded = {}, []
    for f in ("title", "description"):
        t, d = sanitize(n.get(f))
        if d:
            excluded.append(f)
        elif t:
            fields[f] = t
    out = []
    for tag in TAGS:
        if tag == "contractor_opportunity" and item.get("type") == "flip" and item.get("opportunity_kind") != "gov_contract":
            text_ev = []                                          # contractor work is a service-lane / gov-contract notion
        else:
            text_ev = _scan(tag, fields)
        ev = _structured(tag, item) + text_ev
        if not ev:
            continue
        out.append({"tag": tag, "basis": "INFERENCE", "provenance_id": own_prov, "evidence": ev,
                    "note": "inferred from the quoted evidence only; not verified against the item"})
    pivot = build_pivot(fields)
    block = {"tags": out, "evaluated": list(TAGS), "text_checked": sorted(fields),
             "rules_version": RULES_VERSION,
             "note": "a missing tag means no evidence was found, not that it does not apply"}
    if any(pivot.values()):
        block["pivot"] = pivot
    if excluded:
        block["excluded_fields"] = excluded
        block["excluded_note"] = "fields containing instruction-like text were excluded entirely before matching"
    return block
