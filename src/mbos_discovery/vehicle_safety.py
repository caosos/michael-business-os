"""NHTSA records → sourced KB entries / review items (B-17; same admission standard and R23 as the CPSC converter).

* **Recall entry** (kind `failure_mode`): make and model are DISCRETE API fields, so there is no extraction guesswork.
  Text is a template over NHTSA's own fields (campaign, date, component, consequence, remedy, park-it flag).
* **Complaint statistic** (kind `known_weakness`): per vehicle and component, the COUNT of consumer complaints that
  NHTSA holds (with how many mention a fire or crash). It is a count of agency records, worded as unverified consumer
  reports; narratives, VINs and any personal details never leave the raw artifact.
* **Model years (B-18).** Both are year-specific (the query includes `modelYear`). Agent 03's KB matcher supports
  `match[].years` since engine 0.11.0 (C-18): a listing must state a covered year, and no year or an uncovered year
  means NO match (UNKNOWN on the card). Every NHTSA entry therefore carries `years`; a per-year source without
  `years` would be a bug. A recall that NHTSA returns for several queried years is ONE entry (one match group per
  make+model) listing all covered years. If the flag is turned off, entries are held on the REVIEW list instead.
* Also held for review: a model name too short or purely numeric for 03's matcher (Mazda "3"), no consequence or
  remedy text, and any NHTSA wording that trips the elementary-advice lint.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Optional

from . import AGENT_ID, NORMALIZER_VERSION
from .adapter import FetchResult, NormalizationError, SearchProfile, SourceAdapter, SourceError
from .contract import check_provenance
from .health import HealthBook
from .ids import derived_ulid, iso
from .normalize import clean_text
from .rawstore import RawStore
from .recalls import RecallsReport, _ELEMENTARY, _cut, _slug, enforce_unique_ids

KB_SUPPORTS_MODEL_YEARS = True           # Agent 03 engine >= 0.11.0 (C-18, d9bceea): match[].years supported
MIN_COMPLAINTS = 5                        # a component needs at least this many complaints to be reported
YEAR_REVIEW = "recall/complaints are model-year specific and the KB matcher has no year field yet: held for review"


def _date(mdy: str) -> Optional[str]:
    try:
        return datetime.strptime(str(mdy), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def _model_ok(model: str) -> bool:
    m = model.strip()
    return len(m) >= 3 and not m.replace(" ", "").isdigit()


def _prov(adapter: SourceAdapter, key: str, url: str, raw_ref: str, fetched_at: datetime) -> dict:
    prov = {"provenance_id": derived_ulid("prov", fetched_at, "nhtsa", key, raw_ref), "created_at": iso(fetched_at),
            "actor_type": "external", "agent_name": AGENT_ID, "basis": "FACT", "source_uri": url,
            "fetched_at": iso(fetched_at), "tool_name": adapter.tool_name, "tool_version": adapter.adapter_version,
            "config_version": f"normalizer-{NORMALIZER_VERSION}", "inputs_used": [{"ref": url, "hash": raw_ref}]}
    check_provenance(prov)
    return prov


def _finish(entry: dict, rep: RecallsReport, key: str, title: str, prov_id: str, extra_reason: Optional[str]) -> None:
    """Route one candidate entry: elementary lint → human glance; year gate → review; else admit."""
    if any(rx.search(entry["risk"]) for rx in _ELEMENTARY):
        extra_reason = "NHTSA text contains elementary-advice wording; needs a human glance (candidate entry attached)"
    if extra_reason is None and not KB_SUPPORTS_MODEL_YEARS:
        extra_reason = YEAR_REVIEW
    if extra_reason:
        rep.review.append({"recall_id": key, "recall_number": key, "title": title, "reason": extra_reason,
                           "provenance_id": prov_id, "candidate_entry": entry})
    else:
        rep.entries.append(entry)


def _years_label(years: list[int]) -> str:
    ys = sorted(set(years))
    return f"{ys[0]}–{ys[-1]}" if len(ys) > 2 and ys[-1] - ys[0] == len(ys) - 1 else ", ".join(map(str, ys))


def recall_entry(rec: dict, years: list[int], url: str, ref: dict) -> tuple[Optional[dict], Optional[str]]:
    make, model = clean_text(rec.get("Make")).lower(), clean_text(rec.get("Model"))
    num, date = clean_text(rec.get("NHTSACampaignNumber"), 30), _date(rec.get("ReportReceivedDate"))
    years = sorted(set(years))
    if not (make and model and num and date):
        return None, "recall record lacks make, model, campaign number or a valid date"
    if not _model_ok(model):
        return None, f"model name {model!r} is too short or purely numeric for the KB matcher (needs ≥ 3 chars, not a bare number)"
    cons, remedy = clean_text(rec.get("Consequence"), 1200), clean_text(rec.get("Remedy"), 1200)
    if not cons or not remedy:
        return None, "recall has no consequence or no remedy text"
    flags = [t for t, k in (("do not drive until repaired", "parkIt"), ("park outside", "parkOutSide"),
                            ("remedy is an over-the-air update", "overTheAirUpdate")) if rec.get(k) is True]
    risk = (f"{_years_label(years)} {make.title()} {model} recall, NHTSA campaign {num} (reported {date}): component "
            f"{clean_text(rec.get('Component'), 160)}. Consequence as stated by NHTSA: {_cut(cons, 300)} "
            f"Remedy as stated by NHTSA: {_cut(remedy, 240)}"
            + (f" NHTSA flags: {', '.join(flags)}." if flags else "")
            + " Whether the remedy was completed on this vehicle is UNKNOWN.")
    return ({"id": f"nhtsa_{num}_{_slug(make)}_{_slug(model)}".lower(), "category": "project_vehicle",
             "match": [{"makes": [make], "models": [model], "years": years}], "kind": "failure_mode", "risk": risk,
             "plan_hint": f"Ask a {make.title()} dealer, with the VIN, whether NHTSA campaign {num} is still open on this "
                          f"vehicle before budgeting related repairs.",
             "source": {"title": f"NHTSA recall {num}: {_years_label(years)} {make.title()} {model}, reported {date}", "url": url,
                        "retrieved": ref["fetched_at"][:10]},
             "evidence": {"provenance_id": ref["provenance_id"], "raw_ref": ref["raw_ref"], "campaign": num,
                          "tool": "mbos_discovery.vehicle_safety"}}, None)


def complaint_entries(results: list[dict], query: dict, url: str, ref: dict) -> list[dict]:
    make, model, year = clean_text(query["make"]).lower(), clean_text(query["model"]), int(query["year"])
    by_comp: Counter = Counter()
    fire: Counter = Counter()
    crash: Counter = Counter()
    for c in results:
        comps = [clean_text(x).upper() for x in str(c.get("components") or "").split(",") if clean_text(x)]
        for comp in comps:
            by_comp[comp] += 1
            fire[comp] += 1 if c.get("fire") is True else 0
            crash[comp] += 1 if c.get("crash") is True else 0
    out = []
    for comp, n in sorted(by_comp.items(), key=lambda kv: (-kv[1], kv[0])):
        if n < MIN_COMPLAINTS:
            continue
        risk = (f"NHTSA holds {n} consumer complaints for the {year} {make.title()} {model} that list the component "
                f"{comp.title()} (of {len(results)} complaints for this vehicle)"
                + (f"; {fire[comp]} mention a fire and {crash[comp]} a crash" if fire[comp] or crash[comp] else "")
                + ". These are unverified consumer reports, not NHTSA findings.")
        out.append({"id": f"nhtsa_complaints_{_slug(make)}_{_slug(model)}_{year}_{_slug(comp)}", "category": "project_vehicle",
                    "match": [{"makes": [make], "models": [model], "years": [year]}], "kind": "known_weakness", "risk": risk,
                    "plan_hint": f"Treat {comp.title()} as a known complaint area for this model year; inspect it specifically.",
                    "source": {"title": f"NHTSA complaints database: {year} {make.title()} {model}, {len(results)} records as of "
                                        f"{ref['fetched_at'][:10]}", "url": url, "retrieved": ref["fetched_at"][:10]},
                    "evidence": {"provenance_id": ref["provenance_id"], "raw_ref": ref["raw_ref"], "complaints": n,
                                 "tool": "mbos_discovery.vehicle_safety"}})
    return out


def collect(adapter: SourceAdapter, profile: SearchProfile, raw: RawStore, health: HealthBook, now: datetime,
            enabled_sources: frozenset[str] = frozenset(), panic=None) -> RecallsReport:
    """Same gate and failure isolation as discovery (policy → lane → freeze → lane E PANIC; fail closed)."""
    from .pipeline import gate
    rep = RecallsReport()
    row = {"source": adapter.source, "status": "ok", "recalls": 0, "complaint_queries": 0, "entries": 0, "review": 0,
           "quarantined": 0}
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
        row.update(status="error", error={"kind": res.error.kind, "status": res.error.status, "message": res.error.message[:300]})
        fr = health.record_failure(adapter.source, now, res.error)
        if fr:
            rep.freeze_requests.append(fr)
        return rep
    groups: dict[tuple, dict] = {}               # (campaign, make, model) -> merged recall across queried years
    for r in res.records:
        raw_ref = raw.put(r.raw_bytes)
        try:
            p = r.payload
            if not isinstance(p, dict) or p.get("endpoint") not in ("recalls", "complaints") or not str(p.get("url", "")).startswith("https://api.nhtsa.gov/"):
                raise NormalizationError("not a recognised NHTSA payload")
            key = (p["record"].get("NHTSACampaignNumber") if p["endpoint"] == "recalls" else
                   f"complaints-{p['query']['make']}-{p['query']['model']}-{p['query']['year']}")
            prov = _prov(adapter, str(key), p["url"], raw_ref, r.fetched_at)
        except Exception as e:  # noqa: BLE001
            row["quarantined"] += 1
            rep.quarantine.append({"raw_ref": raw_ref, "error": f"{type(e).__name__}: {e}"[:300]})
            continue
        rep.provenance.setdefault(prov["provenance_id"], prov)
        ref = {"fetched_at": iso(r.fetched_at), "raw_ref": raw_ref, "provenance_id": prov["provenance_id"]}
        if p["endpoint"] == "recalls":
            row["recalls"] += 1
            rep.records[str(key)] = {"endpoint": "recalls", "query": p["query"], "url": p["url"], **ref}
            gk = (str(key), clean_text(p["record"].get("Make")).lower(), clean_text(p["record"].get("Model")).lower())
            g = groups.setdefault(gk, {"rec": p["record"], "years": set(), "url": p["url"], "ref": ref,
                                       "prov": prov["provenance_id"], "key": str(key)})
            g["years"].add(int(p["query"]["year"]))
        else:
            row["complaint_queries"] += 1
            rep.records[str(key)] = {"endpoint": "complaints", "query": p["query"], "url": p["url"], "count": len(p["results"]), **ref}
            for e in complaint_entries(p["results"], p["query"], p["url"], ref):
                _finish(e, rep, e["id"], e["source"]["title"], prov["provenance_id"], None)
    for g in groups.values():                    # one entry per (campaign, make, model) with all covered years
        entry, reason = recall_entry(g["rec"], sorted(g["years"]), g["url"], g["ref"])
        title = clean_text(g["rec"].get("Component"), 120) or g["key"]
        if entry is None:
            rep.review.append({"recall_id": g["key"], "recall_number": g["key"], "title": title, "reason": reason,
                               "provenance_id": g["prov"]})
        else:
            _finish(entry, rep, g["key"], title, g["prov"], None)
    rep.entries.sort(key=lambda e: e["id"])
    enforce_unique_ids(rep)
    row.update(entries=len(rep.entries), review=len(rep.review))
    health.record_success(adapter.source, now, len(res.records))
    return rep
