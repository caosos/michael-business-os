"""C-16: the card's ``value_add`` block: a plan plus SOURCED model-specific risks (ADR-0011 R18).

``build_value_add(item, as_of, cfg=, priors=, kb=, make_model=)`` is pure and deterministic and returns the
data for ``spine.record_enrichment(conn, item_id, "value_add", block, provenance_id, agent="agent-03-economics")``::

    {"plan": {"value": "...", "basis": "INFERENCE", "provenance_id": "prov_..."},
     "model_specific_risks": [{"risk", "kind", "basis", "source", "provenance_id"}, ...]}

Michael is an experienced mechanic. The knowledge base (``config/value_add_kb.json``) holds NO general advice,
only facts tied to a named model and a primary source. Rules:

* a model with no KB entry yields NO risks: absent knowledge is UNKNOWN, never a guess;
* a risk is emitted only when a make AND a model token from the entry appear in the listing (word-bounded,
  case-insensitive, hyphen/space tolerant); the text is seller-stated and unverified, and the risk says so;
* the plan is built from the deal's own numbers (budget, parts ceiling, sold-comp target) and from the matched
  entries' ``plan_hint``; never from free text.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from . import __version__ as VERSION
from .canonical import content_hash, derived_ulid
from .config import CONFIG_DIR, ScoringConfig
from .engine import _bisect_int, compute
from .inputs import build_engine_input
from .numeric import D

KB_FORMAT = 1
TOOL_NAME = "mbos_economics.valueadd"


def load_kb(path: Path | None = None) -> dict:
    p = Path(path) if path else CONFIG_DIR / "value_add_kb.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    if doc.get("kb_format") != KB_FORMAT:
        raise ValueError(f"value-add KB must be kb_format {KB_FORMAT}")
    for e in doc["entries"]:                        # a risk without a primary source cannot exist
        src = e.get("source") or {}
        if not (e.get("risk") and e.get("kind") and src.get("url", "").startswith("https://") and src.get("title")):
            raise ValueError(f"KB entry {e.get('id')!r} needs risk, kind and a titled https source")
    doc["_hash"] = content_hash({k: v for k, v in doc.items() if k != "_hash"})
    return doc


def _token_re(token: str) -> re.Pattern:
    """Word-bounded, case-insensitive; a hyphen or space inside a model token tolerates either (or none)."""
    parts = [re.escape(c) if c not in " -" else r"[\s\-]?" for c in token.lower()]
    return re.compile(r"(?<![a-z0-9])" + "".join(parts) + r"(?![a-z0-9])")


def match_entries(item: dict, kb: dict, make_model: str | None = None) -> list[dict]:
    text = " ".join([(item.get("normalized") or {}).get("title") or "", make_model or ""]).lower()
    hits = []
    for e in kb["entries"]:
        if e["category"] != item.get("category"):
            continue
        for g in e["match"]:
            make_ok = not g.get("makes") or any(_token_re(m).search(text) for m in g["makes"])
            if make_ok and any(_token_re(m).search(text) for m in g["models"]):
                hits.append(e)
                break
    return hits


def _parts_ceiling(item: dict, cfg: ScoringConfig) -> int | None:
    """Highest whole-dollar parts budget at which every hard gate passes and the expected $/h and profit still
    clear the targets (evidence conditions outstanding are ignored)."""
    inp = build_engine_input(item)
    cap = int(D(inp["economics"]["resale"]["target_sell_price"]))

    def ok(parts: int) -> bool:
        trial = copy.deepcopy(inp)
        trial["economics"]["rehab"]["parts_cost"] = parts
        r = compute(trial, cfg)
        return all(r["gates"].values()) and r["yes_conditions"]["ev_pph_target_ok"] and r["yes_conditions"]["ev_min_profit_ok"]

    return _bisect_int(0, cap, ok, want_max=True)


def _binding(item: dict, cfg: ScoringConfig) -> str:
    """What actually stops the deal when even $0 of parts will not do (never blame the wrong limit)."""
    inp = build_engine_input(item)
    inp["economics"]["rehab"]["parts_cost"] = 0
    r = compute(inp, cfg)
    cap = cfg.num("capital_and_risk.risk_capital_per_deal_cap")
    text = {
        "cash_ok": f"your ${cap:,.0f} per-deal cash limit (it ties up ${r['derived']['cash_tied_up']:,.0f})",
        "max_loss_ok": f"your ${cfg.num('capital_and_risk.max_loss_cap'):,.0f} worst-case loss limit",
        "pph_floor_ok": f"your ${cfg.num('time_value.w_min_per_hour'):g}/h floor",
        "min_profit_ok": "the minimum profit",
        "ev_positive": "a positive expected value",
        "skill_ok": "your skill profile", "license_ok": "a license you do not hold",
        "distance_ratio_ok": "the travel-to-profit limit at this distance",
    }
    failed = [g for g, ok in r["gates"].items() if not ok]
    if failed:
        return "fails " + " and ".join(text[g] for g in failed)
    return f"does not clear your ${cfg.num('time_value.w_target_flip_per_hour'):g}/h flip target at the current buy price"


def _usd(x) -> str:
    return f"${D(x):,.0f}"


def _plan(item: dict, cfg: ScoringConfig, hints: list[str]) -> tuple[str | None, str | None]:
    """(plan text, omitted reason). Built only from the deal's own numbers and sourced plan hints."""
    sc = (item.get("scores") or {}).get("scorecard")
    econ = item.get("economics") or {}
    if not sc or sc.get("lane") != "flip" or not econ.get("rehab") or not econ.get("resale"):
        return None, "plan: needs a scored flip with a repair estimate"
    rehab, d = econ["rehab"], sc["derived"]
    target = cfg.num("time_value.w_target_flip_per_hour")
    scope = "" if rehab.get("repair_scope_known") else " (a category estimate; the fault is not diagnosed yet)"
    lines = [f"Budget about {_usd(rehab['parts_cost'])} in parts and {_usd(rehab['materials_cost'])} in materials plus "
             f"about {D(rehab['labor_hours']):g} h of your time{scope}."]
    ceiling = _parts_ceiling(item, cfg)
    if ceiling is None:
        lines.append(f"Even with no parts spend this {_binding(item, cfg)}.")
    else:
        lines.append(f"Parts can run up to {_usd(ceiling)} before the deal drops below your ${target:g}/h flip target.")
    if D(d.get("transport_extra_cash", 0)) or D(d.get("transport_extra_hours", 0)):
        lines.append(f"The trailer run is already costed in ({_usd(d['transport_extra_cash'])} and {D(d['transport_extra_hours']):g} h).")
    fact = [r for r in item.get("research") or [] if r.get("basis") == "FACT" and r.get("field") == "resale.target_sell_price"]
    comps = (econ.get("estimates_meta") or {}).get("comps") or []
    if fact and comps:
        lines.append(f"Sell target is {_usd(econ['resale']['target_sell_price'])}, the median of {len(comps)} sold comparables.")
    lines.extend(hints)
    return " ".join(lines), None


def build_value_add(item: dict, as_of: str, *, cfg: ScoringConfig, kb: dict | None = None,
                    make_model: str | None = None) -> dict:
    """Return ``{"block", "provenance", "omitted", "matched", "value_add_hash"}``. Pure; ``block`` is {} when
    nothing can be supported."""
    kb = kb or load_kb()
    sc = item.get("scores") or {}
    hits = match_entries(item, kb, make_model)
    key = content_hash({"spec": "mbos.economics.valueadd/v1", "v": VERSION, "as_of": as_of, "item_id": item.get("item_id"),
                        "inputs_hash": sc.get("inputs_hash"), "kb": kb["_hash"], "config": cfg.hash,
                        "make_model": make_model, "matched": [e["id"] for e in hits]})
    pid = derived_ulid("prov", as_of, "valueadd|" + key)
    omitted: list[str] = []
    block: dict = {}

    plan_text, why_not = _plan(item, cfg, [e["plan_hint"] for e in hits if e.get("plan_hint")])
    if plan_text:
        block["plan"] = {"value": plan_text, "basis": "INFERENCE", "provenance_id": pid}
    else:
        omitted.append(why_not)

    risks = []
    for e in hits:
        s = e["source"]
        risks.append({"risk": e["risk"] + " (Model taken from the listing text; not verified against the unit.)",
                      "kind": e["kind"], "basis": "FACT", "source": f"{s['title']} <{s['url']}> (retrieved {s['retrieved']})",
                      "provenance_id": pid})
    if risks:
        block["model_specific_risks"] = risks
    elif item.get("type") == "flip":
        omitted.append(f"model_specific_risks: no sourced knowledge for this model (KB {kb['kb_version']}); UNKNOWN, not guessed")

    provenance = {
        "provenance_id": pid, "created_at": as_of, "actor_type": "system", "agent_name": "agent-03-economics",
        "basis": "INFERENCE", "tool_name": TOOL_NAME, "tool_version": VERSION, "config_version": kb["kb_version"],
        "inputs_used": [{"ref": "scorecard.inputs_hash", "hash": sc.get("inputs_hash") or "sha256:" + "0" * 64},
                        {"ref": f"value_add_kb@{kb['kb_version']}", "hash": kb["_hash"]}],
        **({"derived_from": sorted({x["provenance_id"] for x in item.get("sources", []) if x.get("provenance_id")})}
           if item.get("sources") else {}),
    }
    return {"block": block, "provenance": provenance, "omitted": omitted, "matched": [e["id"] for e in hits],
            "value_add_hash": key}
