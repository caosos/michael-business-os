"""A-61: owner-local, append-only store for FULL listing-linked decision cases (ARYA-2116/2117/2118), with readback, correction, reset/disable and
a proposal-first retrieval. No database, no network, no GitHub: the file lives under `var/private/decision_cases/` (git-ignored, mode 0600).

Why a new store: `Outcome` needs a spine Item and a fixed outcome kind, `record_attestation` / `record_human_input` are narrow (300-char note, fixed keys),
operator notes are make+model knowledge, cached /market lots are not spine Items, and the resale Book is in memory. Nothing existing holds a whole case
without being misused as an acquisition or a false verification, so this adds the smallest missing piece and reuses the repo's conventions: MBOS-CJSON-1
hashing (`mbos.hashing`), append-only rows with a hash chain, corrections that append, and an explicit reset/disable.

    python -m mbos.decision_cases template                 print a value-free import template
    python -m mbos.decision_cases import FILE              append the case(s) in a LOCAL json file (never prints their contents)
    python -m mbos.decision_cases show LISTING_ID          read back the effective case (corrections applied) + history
    python -m mbos.decision_cases correct LISTING_ID FILE  append a correction (changed fields only); history is kept
    python -m mbos.decision_cases reset LISTING_ID --why T learned use of that case stops; the rows stay for audit
    python -m mbos.decision_cases disable|enable --why T   switch ALL learned use off/on
    python -m mbos.decision_cases verify                   check the hash chain
    python -m mbos.decision_cases diagnose                 per-row integrity report (ids and hashes only; history is never discarded)
    (show/correct/outcome/reset take --source S; a bare listing id is accepted only when one source has it)
    python -m mbos.decision_cases propose CANDIDATE_FILE   proposal-first precedent lookup for a similar candidate

Nothing here bids, buys, contacts anyone, syncs an account or overrides a filter: a proposal is a precedent for the owner to review.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mbos.decision_case_schema import (CASE_KEYS, DECISIONS, EVIDENCE_KINDS, MAX_TEXT, KINDS, PROVENANCE, CaseError, _s, validate_case)  # noqa: F401
from mbos.hashing import sha256_of

ROOT = Path(__file__).resolve().parents[2]
GENESIS = "sha256:" + "0" * 64
def store_dir() -> Path:
    return Path(os.environ.get("MBOS_DECISION_CASES_DIR") or ROOT / "var" / "private" / "decision_cases")


def _log() -> Path:
    return store_dir() / "cases.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


def _in_git(path: Path) -> Optional[Path]:
    base = path
    while not base.is_dir():                       # a store that does not exist yet: use its nearest existing parent
        base = base.parent
    r = _git("rev-parse", "--show-toplevel", cwd=base)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def _must_be_private(path: Path, what: str) -> None:
    """A private path inside a git checkout must be ignored and untracked, so a plain `git add -A` can never publish it."""
    top = _in_git(path)
    if top is None:
        return
    if _git("ls-files", "--error-unmatch", str(path), cwd=top).returncode == 0:
        raise CaseError(f"{what} {path} is TRACKED by git; refusing")
    if _git("check-ignore", "-q", str(path), cwd=top).returncode != 0:
        raise CaseError(f"{what} {path} is inside a git checkout and not git-ignored; refusing (it could be committed)")


# ---------------------------------------------------------------- the append-only chain
class IntegrityError(CaseError):
    """The stored history does not verify: nothing is read back as valid and nothing is applied until the owner inspects it (`diagnose`)."""


class AmbiguousListing(CaseError):
    pass


def rows() -> list[dict]:
    """Every stored row, UNVERIFIED. A line that is not a JSON object becomes {"_malformed": line_no} so nothing is silently discarded."""
    p = _log()
    out = []
    for n, line in enumerate(p.read_text().splitlines() if p.exists() else [], 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            out.append(r if isinstance(r, dict) else {"_malformed": n})
        except ValueError:
            out.append({"_malformed": n})
    return out


def diagnose() -> list[dict]:
    """Per row: ok or what is wrong. Shows seq/kind/listing/source and hashes only, never the case text."""
    prev, out = GENESIS, []
    for n, r in enumerate(rows(), 1):
        if "_malformed" in r:
            out.append({"row": n, "ok": False, "problem": "malformed (not a JSON object)"})
            prev = None
            continue
        body = {k: v for k, v in r.items() if k != "row_hash"}
        try:
            good = r.get("seq") == n and r.get("prev_hash") == prev and r.get("row_hash") == sha256_of(body) and r.get("kind") in KINDS and isinstance(r.get("body"), dict)
        except Exception:  # noqa: BLE001  (a value the canonical hasher refuses is a broken row)
            good = False
        out.append({"row": n, "ok": bool(good), "kind": r.get("kind"), "listing_id": r.get("listing_id"), "source": r.get("source") or (r.get("body") or {}).get("source"),
                    "stored_hash": str(r.get("row_hash"))[:19], "problem": None if good else "row or chain hash mismatch / bad shape"})
        prev = r.get("row_hash") if good else None
    return out


def verify() -> tuple[bool, str]:
    d = diagnose()
    bad = [x for x in d if not x["ok"]]
    return (False, f"chain broken at row {bad[0]['row']}") if bad else (True, f"{len(d)} rows, chain ok")


def good_rows() -> list[dict]:
    """The rows, but only if the whole history verifies; otherwise an explicit integrity failure."""
    ok, msg = verify()
    if not ok:
        raise IntegrityError("INTEGRITY FAILURE: " + msg + " (run `diagnose`; history is kept, nothing is applied or read back as valid)")
    return rows()


def _append(kind: str, listing_id: Optional[str], body: dict, entered_by: str, why: str = "", source: Optional[str] = None) -> dict:
    d = store_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    _must_be_private(d, "the case store")
    cur = good_rows()                                         # refuses to append to a broken chain
    r = {"seq": len(cur) + 1, "prev_hash": cur[-1]["row_hash"] if cur else GENESIS, "kind": kind, "listing_id": listing_id, "source": source, "entered_by": entered_by,
         "entered_at": _now(), "why": why, "body": body}
    r["row_hash"] = sha256_of(r)
    fresh = not _log().exists()
    with open(_log(), "a") as fh:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
    if fresh:
        os.chmod(_log(), 0o600)
    return r


def import_cases(file: Path, entered_by: str = "michael") -> list[dict]:
    file = file.resolve()
    _must_be_private(file, "the import file") if _in_git(file) else None
    data = json.loads(file.read_text())
    cases = [validate_case(c) for c in (data if isinstance(data, list) else [data])]       # validate ALL before writing any
    keys = [(c["source"], c["listing_id"]) for c in cases]
    if len(set(keys)) != len(keys):
        raise CaseError("the same source + listing_id appears twice in this import; nothing was written")
    existing = {(r["body"]["source"], r["listing_id"]) for r in good_rows() if r["kind"] == "case"}
    if existing & set(keys):
        raise CaseError("a case for that source + listing already exists: use `correct`, history is never overwritten")
    return [_append("case", c["listing_id"], c, entered_by, source=c["source"]) for c in cases]


def _case_row(listing_id: str, source: Optional[str] = None, rs: Optional[list[dict]] = None) -> Optional[dict]:
    """The one case for source + listing_id. A bare listing_id is accepted only when exactly one source has it; otherwise AmbiguousListing."""
    hits = [r for r in (rs if rs is not None else good_rows()) if r["kind"] == "case" and r["listing_id"] == listing_id and (source is None or r["body"]["source"] == source)]
    if len({h["body"]["source"] for h in hits}) > 1:
        raise AmbiguousListing(f"listing_id {listing_id!r} exists for several sources ({sorted({h['body']['source'] for h in hits})}): give the source")
    return hits[0] if hits else None


def _need(listing_id: str, source: Optional[str]) -> dict:
    c = _case_row(listing_id, source)
    if not c:
        raise CaseError("no case for that source + listing")
    return c


def correct(listing_id: str, patch: dict, why: str, entered_by: str = "michael", source: Optional[str] = None) -> dict:
    case = _need(listing_id, source)
    p = validate_case(patch, partial=True)
    p.pop("listing_id", None)
    if "source" in p and p["source"] != case["body"]["source"]:
        raise CaseError("a correction cannot change the source identity of a case")
    p.pop("source", None)
    if not p or not why.strip():
        raise CaseError("a correction needs changed fields and a reason")
    return _append("correction", listing_id, p, entered_by, why, case["body"]["source"])


def outcome(listing_id: str, text: str, entered_by: str = "michael", source: Optional[str] = None) -> dict:
    case = _need(listing_id, source)
    return _append("outcome", listing_id, {"text": _s(text, "outcome text"), "label": "owner_reported_actual"}, entered_by, source=case["body"]["source"])


def reset(listing_id: str, why: str, entered_by: str = "michael", source: Optional[str] = None) -> dict:
    case = _need(listing_id, source)
    if not why.strip():
        raise CaseError("a reset needs a reason")
    return _append("reset", listing_id, {}, entered_by, why, case["body"]["source"])


def set_enabled(on: bool, why: str, entered_by: str = "michael") -> dict:
    if not why.strip():
        raise CaseError("a reason is required")
    return _append("enable" if on else "disable", None, {}, entered_by, why)


def learning_enabled() -> bool:
    state = True
    for r in good_rows():
        if r["kind"] in ("enable", "disable"):
            state = r["kind"] == "enable"
    return state


def effective(listing_id: str, source: Optional[str] = None) -> Optional[dict]:
    """The case with its corrections applied in order, its outcomes (owner-reported, apart from estimates) and history. Raises IntegrityError on a
    corrupted history and AmbiguousListing for a bare id shared by several sources; None if there is no such case."""
    rs = good_rows()
    first = _case_row(listing_id, source, rs)
    if not first:
        return None
    src = first["body"]["source"]
    view, hist, outs, active = dict(first["body"]), [], [], True
    for r in rs:
        if r["listing_id"] != listing_id or r["seq"] == first["seq"] or r["kind"] == "case":
            continue
        if (r.get("source") or src) != src:                    # another source's rows for the same listing_id are never mixed in
            continue
        hist.append({"seq": r["seq"], "kind": r["kind"], "at": r["entered_at"], "why": r["why"]})
        if r["kind"] == "correction":
            view.update(r["body"])
        elif r["kind"] == "outcome":
            outs.append(r["body"])
        elif r["kind"] == "reset":
            active = False
    return {"case": view, "outcomes": outs, "active": active, "history": hist, "first_seq": first["seq"]}


# ---------------------------------------------------------------- proposal-first retrieval
def _terms(*parts: Any) -> set[str]:
    return {t for p in parts for t in re.findall(r"[a-z0-9]{3,}", str(p or "").lower())} - {"with", "the", "and", "for", "used", "lot", "item"}


def propose(candidate: dict, min_shared: int = 2) -> dict:
    """Precedents from active cases for a similar CANDIDATE. Per-item decisions stay per-item: this reports what the owner decided on THAT listing and why;
    it never turns a pass into a category dislike, never changes a filter or gate, and never produces a bid amount. On a corrupted history it
    returns INTEGRITY_FAILURE and no matches."""
    if not isinstance(candidate, dict) or not candidate.get("listing_id"):
        raise CaseError("the candidate needs a listing_id")
    base = {"status": "PROPOSAL_FOR_OWNER_REVIEW", "candidate": {k: candidate.get(k) for k in ("listing_id", "source", "title")},
            "authority": "A precedent for the owner to review. Not a bid, purchase, contact or filter override; hard filters and evidence gates still apply.", "matches": []}
    try:
        enabled, rs = learning_enabled(), good_rows()
    except IntegrityError as e:
        return {**base, "status": "INTEGRITY_FAILURE", "note": str(e)}
    if not enabled:
        return {**base, "note": "learned use is DISABLED by the owner; nothing applied"}
    cterms = _terms(candidate.get("title"), candidate.get("text"), *(candidate.get("category_tags") or []))
    have_kinds = {e.get("kind") for e in candidate.get("evidence") or []}
    for r in rs:
        if r["kind"] != "case" or (r["listing_id"] == candidate["listing_id"] and candidate.get("source") in (None, r["body"]["source"])):
            continue                                                # a candidate never matches itself
        eff = effective(r["listing_id"], r["body"]["source"])
        if not eff or not eff["active"]:
            continue
        c = eff["case"]
        shared = cterms & _terms(c.get("title"), *(c.get("category_tags") or []))
        if len(shared) < min_shared:
            continue
        est_ev = [{"kind": e["kind"], "text": e["text"], "provenance": "owner_estimate", "presented_as": "an owner ESTIMATE from the source case, not a fact"}
                  for e in c["evidence"] if e["provenance"] == "owner_estimate"]
        base["matches"].append({
            "source_case": {"listing_id": c["listing_id"], "source": c["source"], "decided_at": c["decided_at"], "case_row": eff["first_seq"], "corrections": len([h for h in eff["history"] if h["kind"] == "correction"])},
            "similarity": {"shared_terms": sorted(shared), "score": round(len(shared) / max(1, len(cterms | _terms(c.get("title"), *(c.get("category_tags") or [])))), 3)},
            "precedent_decision": c["decision"], "precedent_scope": "this one listing only; not a category preference",
            "reason_summary": c["reason_summary"],
            "verified_facts": [e for e in c["evidence"] if e["provenance"] == "verified"],
            "unverified_evidence": [e for e in c["evidence"] if e["provenance"] == "unverified"],
            "owner_estimates_not_facts": c.get("owner_estimates", []) + est_ev,
            "uncertainty": c.get("uncertainty", []), "missing_evidence_then": c.get("missing_evidence", []),
            "evidence_kinds_the_case_relied_on_that_the_candidate_lacks": sorted({e["kind"] for e in c["evidence"]} - have_kinds),
            "owner_reported_outcomes": eff["outcomes"]})
    base["matches"].sort(key=lambda m: -m["similarity"]["score"])
    if not base["matches"]:
        base["note"] = "no similar active case; nothing to propose from experience"
    return base


TEMPLATE = {"listing_id": "<stable listing id, e.g. the GSA lot id>", "source": "<gsa|...>", "title": "<listing title>", "decided_at": "<ISO 8601 time>",
            "decision": "pass | watch | pursue", "reason_summary": "<why, a summary of the reasoning, not a transcript>",
            "evidence": [{"kind": "condition|photo|dimensions|capacity|paperwork|cost|sold_comparable|repair_work|other", "text": "<what was known then>",
                          "provenance": "verified | owner_estimate | unverified"}],
            "owner_estimates": [{"label": "<what is estimated>", "amount_usd": None, "note": "<basis>"}], "alternatives_considered": ["<alternative exit>"],
            "uncertainty": ["<what was uncertain>"], "missing_evidence": ["<what was missing>"], "owner_skills": "<skills and actual repair work>",
            "category_tags": ["<tag used to find similar candidates>"]}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    opts = {}
    pos = []
    i = 0
    while i < len(rest):
        if rest[i] in ("--why", "--source") and i + 1 < len(rest):
            opts[rest[i][2:]] = rest[i + 1]
            i += 2
        else:
            pos.append(rest[i])
            i += 1
    why, src = opts.get("why", ""), opts.get("source")
    try:
        if cmd == "template":
            print(json.dumps(TEMPLATE, indent=1))
        elif cmd == "import":
            for r in import_cases(Path(pos[0])):
                print(f"imported {r['source']}/{r['listing_id']} as row {r['seq']} {r['row_hash'][:19]}")
        elif cmd == "show":
            e = effective(pos[0], src)
            print(json.dumps(e, indent=1) if e else "no case for that listing")
            return 0 if e else 1
        elif cmd == "correct":
            print("correction row", correct(pos[0], json.loads(Path(pos[1]).read_text()), why, source=src)["seq"])
        elif cmd == "outcome":
            print("outcome row", outcome(pos[0], pos[1], source=src)["seq"])
        elif cmd == "reset":
            print("reset row", reset(pos[0], why, source=src)["seq"])
        elif cmd in ("disable", "enable"):
            print(cmd, "row", set_enabled(cmd == "enable", why)["seq"])
        elif cmd == "verify":
            ok, msg = verify()
            print(msg)
            return 0 if ok else 1
        elif cmd == "diagnose":
            d = diagnose()
            print(json.dumps(d, indent=1))
            return 0 if all(x["ok"] for x in d) else 1
        elif cmd == "propose":
            out = propose(json.loads(Path(pos[0]).read_text()))
            print(json.dumps(out, indent=1))
            return 3 if out["status"] == "INTEGRITY_FAILURE" else 0
        else:
            print(__doc__)
            return 2
    except IntegrityError as e:
        print("REFUSED:", e)
        return 3
    except (CaseError, OSError, ValueError, IndexError) as e:
        print("REFUSED:", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
