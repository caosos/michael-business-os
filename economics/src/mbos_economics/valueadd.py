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
* Michael's own mechanic notes enter ONLY through the ``manual`` path (``new_manual_note`` ->
  ``load_manual_notes`` -> ``merge_manual``): a note needs a named author, a timestamp, a human provenance record,
  and a make AND model match; it is shown as RECOMMENDATION (owner-stated), never FACT, and can never ship inside the
  packaged KB (``load_kb`` refuses ``origin: manual``);
* the plan is built from the deal's own numbers (budget, parts ceiling, sold-comp target) and from the matched
  entries' ``plan_hint``; never from free text.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from . import __version__ as VERSION
from .canonical import content_hash, derived_ulid, parse_ts
from .config import CONFIG_DIR, ScoringConfig
from .engine import _bisect_int, compute
from .inputs import build_engine_input
from .numeric import D

KB_FORMAT = 1
TOOL_NAME = "mbos_economics.valueadd"


_NUMERIC_ONLY = re.compile(r"^[\d\s\-./]+$")


def weak_match_problems(entry: dict) -> list[str]:
    """Why an entry's match tokens could warn about the WRONG unit. A recall or weak-point warning on a unit that is
    not affected is a false safety claim, so these fail closed:

    * every group needs BOTH makes and models (a model alone is never enough);
    * a model token must not be purely numeric: a wattage, year, gallon size or part count ("6500", "2018", "20")
      appears in unrelated listings of the same make;
    * a model token must be at least 3 characters.
    """
    out: list[str] = []
    for g in entry.get("match") or []:
        if not g.get("makes") or not g.get("models"):
            out.append("a match group needs BOTH makes and models")
        for m in g.get("models") or []:
            if _NUMERIC_ONLY.match(str(m)):
                out.append(f"model token {m!r} is purely numeric (a wattage, year or size, not a model)")
            elif len(str(m).strip()) < 3:
                out.append(f"model token {m!r} is shorter than 3 characters")
    return out


def load_kb(path: Path | None = None) -> dict:
    p = Path(path) if path else CONFIG_DIR / "value_add_kb.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    if doc.get("kb_format") != KB_FORMAT:
        raise ValueError(f"value-add KB must be kb_format {KB_FORMAT}")
    for e in doc["entries"]:                        # a risk without a primary source cannot exist
        if e.get("origin") == "manual":
            raise ValueError(f"KB entry {e.get('id')!r}: manual notes never ship in the KB file; use merge_manual()")
        src = e.get("source") or {}
        if not (e.get("risk") and e.get("kind") and src.get("url", "").startswith("https://") and src.get("title")):
            raise ValueError(f"KB entry {e.get('id')!r} needs risk, kind and a titled https source")
        weak = weak_match_problems(e)
        if weak:
            raise ValueError(f"KB entry {e.get('id')!r} has match tokens that could fire on the wrong unit: {'; '.join(weak)}")
    doc["_hash"] = content_hash({k: v for k, v in doc.items() if k != "_hash"})
    return doc


# --------------------------------------------------------------------------- Michael's own notes (manual path)

NOTES_FORMAT = 1
NOTE_KINDS = {"failure_mode", "expensive_part", "parts_availability", "known_weakness", "resale_demand", "economic"}
NOTE_CATEGORIES = {"trailer", "mower", "generator", "welder", "compressor", "tool", "commercial_equipment",
                   "mechanical_equipment", "project_vehicle", "other_asset"}
MAX_NOTE_CHARS = 600
# Boilerplate an experienced mechanic does not want (same patterns as agent-01 mbos.card.ELEMENTARY_ADVICE).
_ELEMENTARY = [re.compile(p, re.I) for p in (
    r"\bcheck (the )?(engine )?compression\b", r"\bcheck (for )?(a )?spark\b", r"\binspect (the )?fuel\b",
    r"\bcheck (the )?(engine )?oil\b", r"\bcheck (the )?(air )?filter\b", r"\bcheck (the )?(spark ?plug|plugs)\b",
    r"\binspect (the )?(belts?|hoses?)\b", r"\bverify (it )?(starts|runs)\b(?! after)",
    r"\bmake sure (it|the engine) (starts|runs)\b", r"\bcheck (the )?battery\b", r"\blook for (any )?(leaks|damage)\b")]
_PID = re.compile(r"^prov_[0-9A-HJKMNP-TV-Z]{26}$")


class NoteError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _note_problems(n: dict) -> list[str]:
    """Every problem with a note, each check independent (a missing field never hides other faults)."""
    p: list[str] = []
    for k in ("note_id", "category", "match", "kind", "statement", "entered_by", "entered_at", "basis_of_knowledge", "provenance_id"):
        if not n.get(k):
            p.append(f"{k} is required")
    if n.get("category") and n["category"] not in NOTE_CATEGORIES:
        p.append(f"category {n['category']!r} is not a flip category")
    if n.get("kind") and n["kind"] not in NOTE_KINDS:
        p.append(f"kind {n['kind']!r} must be one of {sorted(NOTE_KINDS)}")
    if n.get("provenance_id") and not _PID.match(n["provenance_id"]):
        p.append("provenance_id must be the id of the persisted human provenance record")
    if n.get("entered_at"):
        try:
            parse_ts(n["entered_at"])
        except (TypeError, ValueError):
            p.append("entered_at must be an RFC 3339 timestamp with a timezone")
    m = n.get("match")
    if m is not None and (not isinstance(m, list) or not m or not all(isinstance(g, dict) and g.get("makes") and g.get("models") for g in m)):
        p.append("every match group needs BOTH makes and models (a note must be about a named model)")
    if n.get("basis") not in (None, "RECOMMENDATION"):
        p.append("a manual note is owner-stated: basis is always RECOMMENDATION, never FACT")
    if n.get("reference_url") and not str(n["reference_url"]).startswith("https://"):
        p.append("reference_url must be https")
    if n.get("supersedes") and not re.match(r"^mn_[0-9A-HJKMNP-TV-Z]{26}$", str(n["supersedes"])):
        p.append("supersedes must be the note_id of the note being edited")
    if n.get("supersedes") and n.get("supersedes") == n.get("note_id"):
        p.append("a note cannot supersede itself")
    for k in ("statement", "plan_hint"):
        text = n.get(k) or ""
        if len(text) > MAX_NOTE_CHARS:
            p.append(f"{k} is over {MAX_NOTE_CHARS} characters")
        hit = [m_.group(0) for rx in _ELEMENTARY for m_ in [rx.search(text)] if m_]
        if hit:
            p.append(f"{k} contains elementary advice {hit}: say what is specific to THIS model")
    return p


def new_manual_note(*, category: str, makes: list[str], models: list[str], kind: str, statement: str, entered_by: str,
                    entered_at: str, basis_of_knowledge: str, plan_hint: str | None = None,
                    reference_url: str | None = None, review_after: str | None = None,
                    supersedes: str | None = None) -> dict:
    """Build one validated note plus the HUMAN provenance record the entry step must persist FIRST.
    Pure: writes nothing and reads no clock (``entered_at`` is supplied by the entry channel)."""
    try:                                    # validate the timestamp BEFORE deriving ids from it
        parse_ts(entered_at)
    except (TypeError, ValueError):
        raise NoteError(["entered_at must be an RFC 3339 timestamp with a timezone"]) from None
    body = {"category": category, "match": [{"makes": list(makes), "models": list(models)}], "kind": kind,
            "statement": statement.strip(), "entered_by": entered_by, "entered_at": entered_at,
            "basis_of_knowledge": basis_of_knowledge,
            **({"plan_hint": plan_hint.strip()} if plan_hint else {}),
            **({"reference_url": reference_url} if reference_url else {}),
            **({"review_after": review_after} if review_after else {}),
            **({"supersedes": supersedes} if supersedes else {})}       # an edit: part of the content, so it changes the id
    digest = content_hash(body)
    prov_id = derived_ulid("prov", entered_at, "manual-note|" + digest)
    note = {"note_id": derived_ulid("mn", entered_at, "manual-note|" + digest), **body, "provenance_id": prov_id}
    problems = _note_problems(note)
    if problems:
        raise NoteError(problems)
    provenance = {"provenance_id": prov_id, "created_at": entered_at, "actor_type": "human", "human_actor": entered_by,
                  "basis": "RECOMMENDATION", "tool_name": "mbos.manual_note", "tool_version": VERSION,
                  "inputs_used": [{"ref": note["note_id"], "hash": digest}]}
    return {"note": note, "provenance": provenance}


def load_manual_notes(doc_or_path) -> list[dict]:
    """Validate a notes document ``{"notes_format": 1, "notes": [...]}`` (dict or file path). Retracted notes are
    kept out of the result. Raises NoteError listing every problem; nothing partial is returned."""
    doc = doc_or_path if isinstance(doc_or_path, dict) else json.loads(Path(doc_or_path).read_text(encoding="utf-8"))
    if doc.get("notes_format") != NOTES_FORMAT:
        raise NoteError([f"notes_format must be {NOTES_FORMAT}"])
    problems, out, seen = [], [], set()
    for i, n in enumerate(doc.get("notes") or []):
        if n.get("retracted"):          # out of use: its content is never shown, so its text is not linted (a retraction
            if n.get("note_id") in seen:  # row copies the retracted note, so linting it would make a retraction useless)
                problems.append(f"notes[{i}] duplicate note_id")
            seen.add(n.get("note_id"))
            continue
        errs = _note_problems(n)
        if n.get("note_id") in seen:
            errs.append("duplicate note_id")
        seen.add(n.get("note_id"))
        problems += [f"notes[{i}] {e}" for e in errs]
        if not errs and not n.get("retracted"):
            out.append(n)
    if problems:
        raise NoteError(problems)
    return out


def load_manual_notes_lenient(doc_or_path) -> tuple[list[dict], list[dict]]:
    """For a document read from the STORE: ``(valid_active_notes, problems)``.

    The database accepts any text (the elementary-advice lint lives here, in Python), so one bad note must not switch
    off every other note. Each bad note is skipped and reported as ``{"note_id", "problems"}``; the strict
    ``load_manual_notes`` stays the right tool for ``note check`` and for entry-time validation. A malformed
    document (wrong ``notes_format``) still raises."""
    doc = doc_or_path if isinstance(doc_or_path, dict) else json.loads(Path(doc_or_path).read_text(encoding="utf-8"))
    if doc.get("notes_format") != NOTES_FORMAT:
        raise NoteError([f"notes_format must be {NOTES_FORMAT}"])
    good, bad, seen = [], [], set()
    for n in doc.get("notes") or []:
        if n.get("retracted"):          # out of use: not linted (see load_manual_notes)
            seen.add(n.get("note_id"))
            continue
        errs = _note_problems(n)
        if n.get("note_id") in seen:
            errs.append("duplicate note_id")
        seen.add(n.get("note_id"))
        if errs:
            bad.append({"note_id": n.get("note_id"), "problems": errs})
        else:
            good.append(n)
    return good, bad


def merge_manual(kb: dict, notes: list[dict]) -> dict:
    """A COPY of the KB with the notes appended as ``origin: manual`` entries (sourced entries stay first)."""
    merged = {k: v for k, v in copy.deepcopy(kb).items() if k != "_hash"}
    for n in notes:
        merged["entries"].append({
            "id": f"manual:{n['note_id']}", "origin": "manual", "category": n["category"], "match": n["match"],
            "kind": n["kind"], "risk": n["statement"], "plan_hint": n.get("plan_hint"), "provenance_id": n["provenance_id"],
            "source": {"title": f"{n['entered_by']}'s own note ({n['basis_of_knowledge']}), entered {n['entered_at'][:10]}",
                       "url": n.get("reference_url"), "retrieved": n["entered_at"][:10]}})
    merged["kb_version"] = kb["kb_version"] + "+manual"
    merged["_hash"] = content_hash(merged)
    return merged



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

    risks, manual_pids = [], []
    for e in hits:
        s = e["source"]
        if e.get("origin") == "manual":       # Michael's own note: owner-stated, human provenance, never FACT
            ref = f" <{s['url']}>" if s.get("url") else ""
            risks.append({"risk": e["risk"] + " (Michael's note; the model is taken from the listing text and not verified against the unit.)",
                          "kind": e["kind"], "basis": "RECOMMENDATION", "source": f"{s['title']}{ref}",
                          "provenance_id": e["provenance_id"]})
            manual_pids.append(e["provenance_id"])
            continue
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
        **({"derived_from": sorted({x["provenance_id"] for x in item.get("sources", []) if x.get("provenance_id")} | set(manual_pids))}
           if (item.get("sources") or manual_pids) else {}),
    }
    return {"block": block, "provenance": provenance, "omitted": omitted, "matched": [e["id"] for e in hits],
            "value_add_hash": key}
