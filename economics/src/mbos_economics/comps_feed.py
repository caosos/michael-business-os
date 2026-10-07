"""C-04: sold-comps feed → research bundle → estimate → score.

Division of labour (agreed with Agent 02, 2026-10-07):

* **Lane B (02)** owns the comps *sources* (manual inbox; eBay Marketplace Insights,
  fixture-first), raw retention and comp de-duplication. It emits ``SoldComp`` records::

      {"kind": "sold", "price": 2100, "sold_date": "2026-09-14", "source": "ebay_marketplace_insights",
       "url": "...", "provenance_id": "prov_...", "fetched_at": "...", "raw_ref": "sha256:...",
       "dom_days": 9, "category": "trailer", "title": "...", "condition": "used|parts|new|unknown",
       "location": {...}, "currency": "USD"}

  plus one Provenance v1 record per comp (basis FACT: "the source reported this sale").
* **Lane C (03, this module)** owns selection policy and the bundle that ``estimate_item``
  consumes. Selection is deterministic and fail-closed: a comp is used only if every rule
  below passes, and every rejection is reported with its reason.

Free text: comp and listing titles are matched ONLY against the fixed per-category
vocabulary in ``estimation-priors.json`` (``comps_query``), to reject comps of a
conflicting type/size. Text never becomes a number.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .canonical import parse_ts
from .config import ScoringConfig, load_config
from .engine import score_item
from .estimate import apply_estimate, estimate_item, load_priors

_SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\b")


# --------------------------------------------------------------------------- vocabulary keys

def query_key(category: str, title: str | None, priors: ScoringConfig) -> dict[str, str]:
    """First vocabulary token per group found in ``title`` (lower-case, word-bounded, 'N x M' -> 'NxM')."""
    vocab = priors.get("comps_query").get(category) or {}
    text = _SIZE.sub(lambda m: f"{m.group(1)}x{m.group(2)}", (title or "").lower())
    key: dict[str, str] = {}
    for group in sorted(k for k in vocab if not k.startswith("_") and k != "basis"):
        for token in vocab[group]:
            if re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text):
                key[group] = token
                break
    return key


# --------------------------------------------------------------------------- selection

def _source_policy(source: str, priors: ScoringConfig) -> dict:
    reg = priors.get("comps_sources")
    return reg.get(source) or {"disposition": "unknown"}


def _reject(comp: dict, reason: str) -> dict:
    return {"source": comp.get("source"), "url": comp.get("url"), "provenance_id": comp.get("provenance_id"),
            "reason": reason}


def build_comps_bundle(item: dict, comp_records: list[dict], provenance_records: list[dict], as_of: str, *,
                       base_bundle: dict | None = None, priors: ScoringConfig | None = None,
                       cfg: ScoringConfig | None = None) -> dict:
    """Select comps for ``item`` and return ``{bundle, selected, rejected, subject_key}``. Pure."""
    pri = priors or load_priors()
    scfg = cfg or load_config()
    window = int(scfg.num("comps.recency_window_days"))
    as_of_date = parse_ts(as_of).date()
    prov = {p["provenance_id"]: p for p in provenance_records if isinstance(p, dict) and "provenance_id" in p}
    subject = query_key(item.get("category"), (item.get("normalized") or {}).get("title"), pri)

    selected, rejected, seen = [], [], set()
    # canonical input order, so de-duplication (first wins) never depends on how a source ordered its output
    ordered = sorted(comp_records, key=lambda c: (str(c.get("provenance_id")), str(c.get("source")), str(c.get("url"))))
    for c in ordered:
        src = c.get("source")
        pol = _source_policy(src, pri)
        if pol.get("disposition") != "allowed":
            rejected.append(_reject(c, f"source_refused: {src} is {pol.get('disposition')} (ADR-02-0202)"))
            continue
        if c.get("kind") != pol.get("kind"):
            rejected.append(_reject(c, f"kind {c.get('kind')!r} not reportable by {src} (expects {pol.get('kind')})"))
            continue
        if c.get("category") != item.get("category"):
            rejected.append(_reject(c, f"category {c.get('category')} != {item.get('category')}"))
            continue
        if c.get("currency") != "USD":
            rejected.append(_reject(c, f"currency {c.get('currency')!r} (USD required)"))
            continue
        price = c.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
            rejected.append(_reject(c, "price missing or not positive"))
            continue
        p = prov.get(c.get("provenance_id"))
        if p is None:
            rejected.append(_reject(c, "no provenance record"))
            continue
        if p.get("basis") != "FACT" or not (p.get("source_uri") and p.get("fetched_at")):
            rejected.append(_reject(c, "provenance must be basis FACT with source_uri + fetched_at"))
            continue
        date_field = "sold_date" if c["kind"] == "sold" else "observed_date"
        try:
            d = date.fromisoformat(str(c.get(date_field)))
        except ValueError:
            rejected.append(_reject(c, f"{date_field} missing or invalid"))
            continue
        age = (as_of_date - d).days
        if age < 0:
            rejected.append(_reject(c, f"{date_field} {d} is after as_of"))
            continue
        if age > window:
            rejected.append(_reject(c, f"{date_field} {d} older than {window} days"))
            continue
        comp_key = query_key(c["category"], c.get("title"), pri)
        conflicts = [f"{g}: {subject[g]} vs {comp_key[g]}" for g in subject if g in comp_key and comp_key[g] != subject[g]]
        if conflicts:
            rejected.append(_reject(c, "vocabulary conflict (" + "; ".join(conflicts) + ")"))
            continue
        ident = (src, c.get("url") or c.get("raw_ref") or c["provenance_id"])
        if ident in seen:
            rejected.append(_reject(c, "duplicate (same source + url)"))
            continue
        seen.add(ident)
        selected.append(c)

    def when(c: dict) -> str:
        return str(c.get("sold_date") if c["kind"] == "sold" else c.get("observed_date"))

    selected.sort(key=lambda c: (when(c), str(c.get("source")), str(c.get("url"))), reverse=True)

    def entry(c: dict) -> dict:
        # an ASKING comp never carries a sold_date (it is not a sale); it carries observed_date
        date_key = "sold_date" if c["kind"] == "sold" else "observed_date"
        e = {"kind": c["kind"], "price": c["price"], date_key: when(c), "source": c["source"],
             "provenance_id": c["provenance_id"]}
        for k in ("url", "dom_days", "fetched_at"):
            if c.get(k) is not None:
                e[k] = c[k]
        return e

    bundle = copy.deepcopy(base_bundle or {})
    bundle["comps"] = list(bundle.get("comps", [])) + [entry(c) for c in selected if c.get("condition") != "parts"]
    as_is = [entry(c) for c in selected if c.get("condition") == "parts"]
    if as_is:
        bundle["as_is_comps"] = list(bundle.get("as_is_comps", [])) + as_is
    rejected.sort(key=lambda r: (str(r["provenance_id"]), str(r["source"]), str(r["url"])))
    return {"bundle": bundle, "selected": [c["provenance_id"] for c in selected], "rejected": rejected,
            "subject_key": subject}


# --------------------------------------------------------------------------- fixture source

def load_fixture_comps(path: Path) -> tuple[list[dict], list[dict]]:
    """Fixture-first source in Agent 02's SoldComp shape: ``{"comps": [...], "provenance": [...]}``.
    Read-only; no network. Lane B's real adapters emit the same two lists."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(doc.get("comps", [])), list(doc.get("provenance", []))


# --------------------------------------------------------------------------- the RESEARCH step

def research_step(item: dict, comp_records: list[dict], provenance_records: list[dict], as_of: str, *,
                  base_bundle: dict | None = None, cfg: ScoringConfig | None = None,
                  priors: ScoringConfig | None = None) -> dict:
    """comps → bundle → estimate → score. Pure; proposes a state, persists nothing.

    Returns ``proposed_next_state`` "SCORED" (with ``item`` carrying economics + scores +
    recommendation) or "RESEARCHING" (item unchanged; ``gaps`` say what to research next),
    the comps selection report, every provenance record to persist (used comps, estimate,
    score) and receipt drafts. The spine owns the actual transition and its receipt.
    """
    scfg = cfg or load_config()
    pri = priors or load_priors()
    if item.get("state") not in ("NORMALIZED", "RESEARCHING"):
        raise ValueError(f"research_step expects NORMALIZED or RESEARCHING, got {item.get('state')}")
    sel = build_comps_bundle(item, comp_records, provenance_records, as_of, base_bundle=base_bundle,
                             priors=pri, cfg=scfg)
    used = set(sel["selected"])
    used_prov = [p for p in provenance_records if p.get("provenance_id") in used]
    est = estimate_item(item, sel["bundle"], as_of, priors=pri, scoring_cfg=scfg)
    out: dict[str, Any] = {"comps": {k: sel[k] for k in ("selected", "rejected", "subject_key")},
                           "estimate": {k: est[k] for k in ("status", "gaps", "estimate_hash")}}
    if est["status"] != "estimated":
        out.update(proposed_next_state="RESEARCHING", item=copy.deepcopy(item),
                   provenance_records=used_prov + [est["provenance"]], receipt_drafts=[est["receipt_draft"]])
        return out
    new = apply_estimate(item, est)
    scored = score_item(new, scfg, as_of)
    new["scores"], new["recommendation"] = scored["scores"], scored["recommendation"]
    new["provenance_ids"] = sorted(set(new.get("provenance_ids", [])) | {scored["provenance"]["provenance_id"]})
    new["state"] = "SCORED"
    out.update(proposed_next_state="SCORED", item=new,
               provenance_records=used_prov + [est["provenance"], scored["provenance"]],
               receipt_drafts=[est["receipt_draft"], *scored["receipt_drafts"]])
    return out
