"""Recall records → sourced knowledge-base entries (B-16, hand-off to Agent 03's `value_add` KB).

Two outputs per run:
* **recall records** (`RecallRecord`, one FACT provenance each: "CPSC published this recall", source URI = the recall's
  CPSC URL, fetched_at, tool, raw_ref), retained from the raw payload;
* **KB entries** in Agent 03's format, ONLY when the admission standard can be met mechanically:
  a named make AND at least one model token, a named https source with a title and date, a category in scope, and
  no elementary advice. Everything else goes to a **review list** with the reason. Nothing is guessed to fill a gap:
  empty Model or Manufacturers (common in real CPSC data) → review, never an entry.

Text is a TEMPLATE over CPSC's own fields (title, date, units, the stated hazard, the stated remedy); there is no
free text and no language model. Whether a remedy was completed on a given unit is always stated as UNKNOWN.
Entries cite the recall URL, so they stay sourced; they apply on the listing's own words, which the card says are
unverified (03's standard #6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit

from . import AGENT_ID, NORMALIZER_VERSION
from .adapter import FetchResult, NormalizationError, SearchProfile, SourceAdapter, SourceError
from .contract import check_provenance
from .health import HealthBook
from .ids import derived_ulid, iso
from .normalize import classify, clean_text
from .rawstore import RawStore

IN_SCOPE = frozenset({"trailer", "mower", "generator", "welder", "compressor", "tool", "commercial_equipment",
                      "mechanical_equipment", "project_vehicle"})
_SUFFIX = re.compile(r"\b(inc|llc|l\.l\.c|co|corp|corporation|ltd|limited|company|gmbh|ag|usa|us|north america)\b\.?", re.I)
_OF_PLACE = re.compile(r"\s+of\s+[A-Z][\w .'-]+,\s*[A-Za-z. ]+$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{2,24}$")
_SPLIT = re.compile(r"[,;/\n|]|\band\b|\bor\b", re.I)
_ELEMENTARY = [re.compile(p, re.I) for p in (
    r"\bcheck (the )?(engine )?compression\b", r"\bcheck (for )?(a )?spark\b", r"\binspect (the )?fuel\b",
    r"\bcheck (the )?(engine )?oil\b", r"\bcheck (the )?(air )?filter\b", r"\bcheck (the )?(spark ?plug|plugs)\b",
    r"\binspect (the )?(belts?|hoses?)\b", r"\bmake sure (it|the engine) (starts|runs)\b", r"\bcheck (the )?battery\b",
    r"\blook for (any )?(leaks|damage)\b")]


@dataclass
class RecallRecord:
    recall_id: str
    recall_number: str
    recall_date: str
    title: str
    url: str
    last_publish_date: Optional[str]
    products: list[dict]
    manufacturers: list[str]
    importers: list[str]
    hazards: list[str]
    remedies: list[str]
    remedy_options: list[str]
    fetched_at: str
    raw_ref: str
    provenance_id: str


@dataclass
class RecallsReport:
    records: dict[str, dict] = field(default_factory=dict)         # recall_id -> record
    provenance: dict[str, dict] = field(default_factory=dict)
    entries: list[dict] = field(default_factory=list)              # KB entries (Agent 03 format)
    review: list[dict] = field(default_factory=list)               # {recall_id, reason}
    sources: list[dict] = field(default_factory=list)
    freeze_requests: list[dict] = field(default_factory=list)
    quarantine: list[dict] = field(default_factory=list)


def _d(value) -> Optional[str]:
    s = str(value or "")[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def _names(coll) -> list[str]:
    return [clean_text(x.get("Name"), 300) for x in (coll or []) if isinstance(x, dict) and clean_text(x.get("Name"))]


def parse_recall(rec: dict) -> dict:
    """Whitelisted fields of one CPSC recall (guide v1.3). Raises NormalizationError without id, title, https cpsc url."""
    if not isinstance(rec, dict) or not rec.get("RecallID") or not clean_text(rec.get("Title")):
        raise NormalizationError("CPSC recall missing RecallID/Title")
    url = clean_text(rec.get("URL"))
    u = urlsplit(url)
    if u.scheme != "https" or not (u.hostname or "").endswith("cpsc.gov"):
        raise NormalizationError("CPSC recall has no https cpsc.gov URL; cannot be cited")
    rdate = _d(rec.get("RecallDate"))
    if not rdate:
        raise NormalizationError("CPSC recall has no valid RecallDate")
    products = [{"name": clean_text(p.get("Name"), 200), "model": clean_text(p.get("Model"), 600),
                 "units": clean_text(p.get("NumberOfUnits"), 80)}
                for p in (rec.get("Products") or []) if isinstance(p, dict)]
    return {"recall_id": str(rec["RecallID"]), "recall_number": clean_text(rec.get("RecallNumber"), 40),
            "recall_date": rdate, "title": clean_text(rec["Title"], 300), "url": url,
            "last_publish_date": _d(rec.get("LastPublishDate")), "products": products,
            "manufacturers": _names(rec.get("Manufacturers")), "importers": _names(rec.get("Importers")),
            "hazards": _names(rec.get("Hazards")), "remedies": _names(rec.get("Remedies")),
            "remedy_options": [clean_text(o.get("Option")) for o in (rec.get("RemedyOptions") or [])
                               if isinstance(o, dict) and clean_text(o.get("Option"))]}


def _make(name: str) -> str:
    n = _OF_PLACE.sub("", name)
    n = _SUFFIX.sub("", n)
    return re.sub(r"[\s,.]+$", "", re.sub(r"\s+", " ", n)).strip().lower()


_GENERIC_FIRST = frozenset({"american", "national", "united", "general", "international", "global", "universal",
                            "advanced", "premier", "pro", "power", "tool", "tools", "home", "garden", "outdoor"})


def make_tokens(company: str) -> list[str]:
    """The cleaned company name, plus its first word as the brand a listing would actually use ("Acme Outdoor Power
    Inc." → "acme outdoor power", "acme"). The brand word is only a MATCH CANDIDATE: 03's matcher still needs a
    listed model number, so a broad brand word cannot match on its own. Generic words never count as a brand."""
    full = _make(company)
    first = full.split(" ")[0] if full else ""
    out = [full] if full else []
    if first and first != full and len(first) >= 4 and first not in _GENERIC_FIRST:
        out.append(first)
    return out


_LABEL = re.compile(r"^\s*(?:model\s*(?:number|no|num|#)?s?|models|item\s*(?:number|no)s?|no|#)\b[\s.:#-]*", re.I)


def _model_like(t: str) -> bool:
    """A discrete model identifier: ≥ 3 chars, has a digit AND a letter or hyphen (a purely numeric token such as
    "6500" or "2018" is a wattage/year, not a model: matching it would flag units that are not recalled)."""
    return bool(_MODEL.match(t)) and any(c.isdigit() for c in t) and not t.isdigit()


def model_tokens(text: str) -> list[str]:
    """Conservative: only discrete model-number-like tokens. A leading label ("Model", "Model No.", "#") is stripped
    from each part first, so "Model 17AWCBYS010 and 17AWCBYZ010" yields both. Purely numeric tokens are dropped."""
    out: list[str] = []
    for part in _SPLIT.split(text or ""):
        part = _LABEL.sub("", part.strip()).strip().strip(".")
        words = [part] if " " not in part else part.split()
        for t in words:
            t = t.strip(".,")
            if _model_like(t) and t.upper() not in {x.upper() for x in out}:
                out.append(t)
    return out[:25]


def numeric_only_model_text(text: str) -> bool:
    """True if the Model text has candidate identifiers but every one is purely numeric / too short."""
    parts = [_LABEL.sub("", p.strip()).strip().strip(".") for p in _SPLIT.split(text or "")]
    parts = [w.strip(".,") for p in parts for w in (p.split() or [""]) if w.strip(".,")]
    return bool(parts) and any(any(c.isdigit() for c in w) for w in parts) and not model_tokens(text)


def _cut(s: str, n: int) -> str:
    """Truncate at a word boundary (never mid-sentence fragments like 'caregiver and chi')."""
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0].rstrip(",;: ")
    return cut + "…"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40]


def to_kb_entries(rec: dict, record_ref: dict) -> tuple[list[dict], Optional[str], Optional[dict]]:
    """(entries, review_reason, candidate). Entries only if the admission standard is met mechanically; else
    ([], reason, None). `candidate` is set only for the "needs a human glance" case: the complete entry that was
    withheld because CPSC's own wording tripped the elementary-advice lint."""
    text = " ".join([rec["title"]] + [p["name"] for p in rec["products"]])
    category, matched = classify("flip", text.lower())
    if not matched or category not in IN_SCOPE:
        return [], "category out of scope or unrecognised from title/product names", None
    makes = sorted({t for n in rec["manufacturers"] + rec["importers"] for t in make_tokens(n)})
    if not makes:
        return [], "no manufacturer/importer name in the record: no named make", None
    models: list[str] = []
    for p in rec["products"]:
        models += [m for m in model_tokens(p["model"]) if m.upper() not in {x.upper() for x in models}]
    if not models:
        if any(numeric_only_model_text(p["model"]) for p in rec["products"]):
            return [], "Product.Model has only purely numeric identifiers (wattage/year-like): not a named model", None
        return [], "no discrete model number in Product.Model (empty or free text): no named model", None
    if not rec["hazards"]:
        return [], "no hazard statement in the record", None
    units = next((p["units"] for p in rec["products"] if p["units"]), "")
    remedy = rec["remedies"][0] if rec["remedies"] else ""
    risk = (f"{rec['title']} (CPSC recall {rec['recall_number'] or rec['recall_id']}, {rec['recall_date']}). "
            f"Hazard as stated by CPSC: {_cut(rec['hazards'][0], 300)} "
            f"Listed models: {', '.join(models)}." + (f" Units: {units}." if units else "")
            + (f" Remedy as stated by CPSC: {_cut(remedy, 240)}" if remedy else "")
            + " Whether the remedy was completed on this unit is UNKNOWN.")
    glance = any(rx.search(risk) for rx in _ELEMENTARY)
    entry = {
        "id": f"cpsc_{rec['recall_number'] or rec['recall_id']}_{_slug(max(makes, key=len))}".replace("-", "_"),
        "category": category,
        "match": [{"makes": makes, "models": models}],
        "kind": "failure_mode",
        "risk": risk,
        "plan_hint": f"Ask a {max(makes, key=len).title()} dealer whether the CPSC recall remedy is still open for this unit "
                     f"before budgeting related parts.",
        "source": {"title": f"CPSC: {rec['title']}, recall date {rec['recall_date']}", "url": rec["url"],
                   "retrieved": record_ref["fetched_at"][:10]},
        "evidence": {"provenance_id": record_ref["provenance_id"], "raw_ref": record_ref["raw_ref"],
                     "recall_id": rec["recall_id"], "tool": "mbos_discovery.recalls"},
    }
    if glance:       # CPSC's own wording trips the lint: not shipped, but surfaced with the candidate for a human glance
        return [], "CPSC text contains elementary-advice wording; needs a human glance (candidate entry attached)", entry
    return [entry], None, None


def enforce_unique_ids(rep: "RecallsReport") -> None:
    """Agent 03's `load_kb` refuses a KB with a duplicate entry id (0.11.1), and the matcher keys year evidence by id.
    Keep ids unique before anything is written: the first entry keeps its id; a later entry with the same id goes to the
    review list (it would otherwise collide)."""
    seen: set[str] = set()
    kept = []
    for e in rep.entries:
        if e["id"] in seen:
            rep.review.append({"recall_id": e["id"], "recall_number": e["id"], "title": e["source"]["title"],
                               "reason": "duplicate KB entry id; held so it cannot collide with the first entry",
                               "provenance_id": e["evidence"]["provenance_id"], "candidate_entry": e})
        else:
            seen.add(e["id"])
            kept.append(e)
    rep.entries = kept


def _provenance(adapter: SourceAdapter, rec: dict, raw_ref: str, fetched_at: datetime, request_uri: str) -> dict:
    prov = {"provenance_id": derived_ulid("prov", fetched_at, "recall", rec["recall_id"], raw_ref),
            "created_at": iso(fetched_at), "actor_type": "external", "agent_name": AGENT_ID, "basis": "FACT",
            "source_uri": rec["url"], "fetched_at": iso(fetched_at), "tool_name": adapter.tool_name,
            "tool_version": adapter.adapter_version, "config_version": f"normalizer-{NORMALIZER_VERSION}",
            "inputs_used": [{"ref": request_uri, "hash": raw_ref}]}
    check_provenance(prov)
    return prov


def collect_recalls(adapter: SourceAdapter, profile: SearchProfile, raw: RawStore, health: HealthBook, now: datetime,
                    enabled_sources: frozenset[str] = frozenset(), panic=None) -> RecallsReport:
    """Same gate and failure isolation as discovery (policy → lane → freeze → lane E PANIC; fail closed)."""
    from .pipeline import gate
    rep = RecallsReport()
    row = {"source": adapter.source, "status": "ok", "recalls": 0, "entries": 0, "review": 0, "quarantined": 0}
    rep.sources.append(row)
    why = gate(adapter, profile, health, enabled_sources, panic)
    if why:
        row.update(status="skipped", reason=why)
        return rep
    try:
        res: FetchResult = adapter.fetch(profile)
    except Exception as e:  # noqa: BLE001
        res = FetchResult(adapter.source, error=SourceError("crash", f"{type(e).__name__}: {e}"))
    if not res.ok:
        row.update(status="error", error={"kind": res.error.kind, "status": res.error.status,
                                          "message": res.error.message[:300]})
        fr = health.record_failure(adapter.source, now, res.error)
        if fr:
            rep.freeze_requests.append(fr)
        return rep
    for r in res.records:
        raw_ref = raw.put(r.raw_bytes)
        try:
            if r.payload is None:
                raise NormalizationError("payload unparseable")
            rec = parse_recall(r.payload)
            prov = _provenance(adapter, rec, raw_ref, r.fetched_at, r.request_uri)
        except Exception as e:  # noqa: BLE001
            row["quarantined"] += 1
            rep.quarantine.append({"raw_ref": raw_ref, "error": f"{type(e).__name__}: {e}"[:300]})
            continue
        rep.provenance.setdefault(prov["provenance_id"], prov)
        ref = {"fetched_at": iso(r.fetched_at), "raw_ref": raw_ref, "provenance_id": prov["provenance_id"]}
        rep.records[rec["recall_id"]] = {**rec, **ref}
        entries, reason, candidate = to_kb_entries(rec, ref)
        if entries:
            rep.entries += entries
        else:
            item = {"recall_id": rec["recall_id"], "recall_number": rec["recall_number"], "title": rec["title"],
                    "reason": reason, "provenance_id": prov["provenance_id"]}
            if candidate:
                item["candidate_entry"] = candidate
            rep.review.append(item)
    rep.entries.sort(key=lambda e: e["id"])
    enforce_unique_ids(rep)
    row.update(recalls=len(rep.records), entries=len(rep.entries), review=len(rep.review))
    health.record_success(adapter.source, now, len(res.records))
    return rep
