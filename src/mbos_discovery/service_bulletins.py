"""NHTSA technical service bulletins (downloaded flat file, not an API) → sourced KB entries / review items (P-02-13).

The file is read from a local path the operator downloaded; nothing is fetched here. Same admission standard and R23
as the recall converters: an entry is admitted only when EVERY field is present and valid, otherwise the row stays on
the review list with the reason (and, when it is only the text that tripped a lint, the candidate entry).

* One entry (kind `known_weakness`) per (bulletin, make, model), listing every model year the file gives it.
* Required: bulletin number, make, model (≥ 3 chars, not a bare number), one numeric model year (9999 = "all years" is
  not a year, so the row is held), component, summary, valid date.
* Text is a template over the file's own fields. The summary is untrusted: instruction-like text holds the row; the
  bulletin is worded as a manufacturer's service procedure, never as a confirmed defect on a given vehicle.
* Provenance (FACT): the download URL given by the operator plus the sha256 of the file's exact bytes (`raw_ref`).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from . import AGENT_ID, NORMALIZER_VERSION
from .contract import check_provenance
from .ids import derived_ulid, iso
from .normalize import clean_text
from .rawstore import RawStore
from .recalls import RecallsReport, _cut, _slug, enforce_unique_ids
from .tags import sanitize
from .vehicle_safety import _finish, _model_ok, _years_label

TOOL = "mbos_discovery.service_bulletins"
DOWNLOAD_PAGE = "https://www.nhtsa.gov/nhtsa-datasets-and-apis"
COLUMNS = ("NHTSA_ITEM_NUMBER", "MAKE", "MODEL", "MODEL_YEAR", "COMPONENT", "SUMMARY", "BULLETIN_DATE")


def _date(s: str):
    try:
        return datetime.strptime(s.strip(), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _problem(row: dict) -> str | None:
    """Why this row is incomplete (None when complete)."""
    miss = [c for c in ("NHTSA_ITEM_NUMBER", "MAKE", "MODEL", "COMPONENT") if not clean_text(row.get(c))]
    if miss:
        return "bulletin row lacks " + ", ".join(m.lower() for m in miss)
    if not _model_ok(clean_text(row["MODEL"])):
        return f"model name {clean_text(row['MODEL'])!r} is too short or purely numeric for the KB matcher"
    y = clean_text(row.get("MODEL_YEAR"))
    if not (y.isdigit() and 1950 <= int(y) <= 2035):
        return f"model year {y!r} is not a single valid year (an all-years marker cannot be matched)"
    if not _date(row.get("BULLETIN_DATE") or ""):
        return "bulletin date is missing or not YYYYMMDD"
    if not clean_text(row.get("SUMMARY")):
        return "bulletin has no summary text"
    return None


def collect_bulletins(path: Path, raw: RawStore, now: datetime, source_url: str = DOWNLOAD_PAGE) -> RecallsReport:
    rep = RecallsReport()
    row_ct = {"source": "nhtsa_tsb_file", "status": "ok", "rows": 0, "entries": 0, "review": 0, "quarantined": 0}
    rep.sources.append(row_ct)
    data = Path(path).read_bytes()
    raw_ref = raw.put(data)
    prov = {"provenance_id": derived_ulid("prov", now, "nhtsa_tsb", raw_ref), "created_at": iso(now),
            "actor_type": "external", "agent_name": AGENT_ID, "basis": "FACT", "source_uri": source_url,
            "fetched_at": iso(now), "tool_name": TOOL, "tool_version": NORMALIZER_VERSION,
            "config_version": f"normalizer-{NORMALIZER_VERSION}", "inputs_used": [{"ref": source_url, "hash": raw_ref}]}
    check_provenance(prov)
    rep.provenance[prov["provenance_id"]] = prov
    reader = csv.DictReader(io.StringIO(data.decode("utf-8", "replace")), delimiter="\t")
    if not set(COLUMNS) <= set(reader.fieldnames or ()):
        row_ct.update(status="error", error="file lacks the expected columns: " + ", ".join(COLUMNS))
        rep.quarantine.append({"raw_ref": raw_ref, "error": "unrecognised bulletin file layout"})
        row_ct["quarantined"] = 1
        return rep
    groups: dict[tuple, dict] = {}
    for row in reader:
        row_ct["rows"] += 1
        num = clean_text(row.get("NHTSA_ITEM_NUMBER"), 30)
        why = _problem(row)
        if why:
            rep.review.append({"recall_id": num or f"row-{row_ct['rows']}", "recall_number": num, "reason": why,
                               "title": clean_text(row.get("COMPONENT"), 120) or "service bulletin", "provenance_id": prov["provenance_id"]})
            continue
        summary, flagged = sanitize(row["SUMMARY"])
        if flagged:
            rep.review.append({"recall_id": num, "recall_number": num, "title": clean_text(row["COMPONENT"], 120),
                               "reason": "summary contains instruction-like text; excluded entirely, needs a human glance",
                               "provenance_id": prov["provenance_id"]})
            continue
        g = groups.setdefault((num, clean_text(row["MAKE"]).lower(), clean_text(row["MODEL"])),
                              {"row": row, "summary": summary, "years": set()})
        g["years"].add(int(clean_text(row["MODEL_YEAR"])))
    for (num, make, model), g in groups.items():
        years, row = sorted(g["years"]), g["row"]
        date, comp = _date(row["BULLETIN_DATE"]), clean_text(row["COMPONENT"], 160)
        risk = (f"{_years_label(years)} {make.title()} {model}: the manufacturer issued service bulletin {num} (dated {date}) "
                f"for component {comp}. Bulletin summary as filed with NHTSA: {_cut(g['summary'], 300)} "
                "A bulletin is a service procedure, not a recall or a finding that this vehicle is affected. "
                "Whether this vehicle was serviced is UNKNOWN.")
        entry = {"id": f"nhtsa_tsb_{num}_{_slug(make)}_{_slug(model)}".lower(), "category": "project_vehicle",
                 "match": [{"makes": [make], "models": [model], "years": years}], "kind": "known_weakness", "risk": risk,
                 "plan_hint": f"Ask a {make.title()} dealer, with the VIN, whether service bulletin {num} was performed before "
                              f"budgeting related repairs.",
                 "source": {"title": f"NHTSA service bulletin {num}: {_years_label(years)} {make.title()} {model}, dated {date}",
                            "url": source_url, "retrieved": iso(now)[:10]},
                 "evidence": {"provenance_id": prov["provenance_id"], "raw_ref": raw_ref, "bulletin": num, "tool": TOOL}}
        rep.records[num] = {"endpoint": "tsb_file", "url": source_url, "provenance_id": prov["provenance_id"], "raw_ref": raw_ref}
        _finish(entry, rep, num, entry["source"]["title"], prov["provenance_id"], None)
    rep.entries.sort(key=lambda e: e["id"])
    enforce_unique_ids(rep)
    row_ct.update(entries=len(rep.entries), review=len(rep.review))
    return rep
