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

from mbos.hashing import sha256_of

ROOT = Path(__file__).resolve().parents[2]
GENESIS = "sha256:" + "0" * 64
DECISIONS = ("pass", "watch", "pursue")
PROVENANCE = ("verified", "owner_estimate", "unverified")
EVIDENCE_KINDS = ("condition", "photo", "dimensions", "capacity", "paperwork", "cost", "sold_comparable", "repair_work", "other")
CASE_KEYS = {"listing_id", "source", "title", "decided_at", "decision", "reason_summary", "evidence", "owner_estimates", "alternatives_considered",
             "uncertainty", "missing_evidence", "owner_skills", "category_tags", "outcome"}
MAX_TEXT = 4000


class CaseError(ValueError):
    pass


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


def _s(v: Any, name: str, required: bool = True) -> str:
    if v is None or v == "":
        if required:
            raise CaseError(f"{name} is required")
        return ""
    if not isinstance(v, str) or len(v) > MAX_TEXT:
        raise CaseError(f"{name} must be text of at most {MAX_TEXT} characters")
    return v.strip()


def _list(v: Any, name: str) -> list:
    if v in (None, ""):
        return []
    if not isinstance(v, list):
        raise CaseError(f"{name} must be a list")
    return v


def validate_case(c: Any, *, partial: bool = False) -> dict:
    """A complete case, or (partial=True) only the fields a correction changes. Owner estimates can never be labelled verified."""
    if not isinstance(c, dict):
        raise CaseError("a case must be a JSON object")
    extra = set(c) - CASE_KEYS
    if extra:
        raise CaseError(f"unknown fields: {sorted(extra)}")
    out: dict = {}
    for k in ("listing_id", "source", "reason_summary"):
        if k in c or not partial:
            out[k] = _s(c.get(k), k)
    for k in ("title", "owner_skills"):
        if k in c:
            out[k] = _s(c[k], k, False)
    if "decided_at" in c or not partial:
        out["decided_at"] = _s(c.get("decided_at"), "decided_at")
        try:
            datetime.fromisoformat(out["decided_at"].replace("Z", "+00:00"))
        except ValueError:
            raise CaseError("decided_at must be an ISO 8601 time")
    if "decision" in c or not partial:
        if c.get("decision") not in DECISIONS:
            raise CaseError(f"decision must be one of {DECISIONS}")
        out["decision"] = c["decision"]
    if "evidence" in c or not partial:
        ev = _list(c.get("evidence"), "evidence")
        if not ev and not partial:
            raise CaseError("evidence needs at least one entry (kind, text, provenance)")
        out["evidence"] = []
        for e in ev:
            if not isinstance(e, dict) or e.get("kind") not in EVIDENCE_KINDS or e.get("provenance") not in PROVENANCE:
                raise CaseError(f"each evidence entry needs kind in {EVIDENCE_KINDS} and provenance in {PROVENANCE}")
            out["evidence"].append({"kind": e["kind"], "text": _s(e.get("text"), "evidence text"), "provenance": e["provenance"]})
    if "owner_estimates" in c:
        out["owner_estimates"] = []
        for e in _list(c["owner_estimates"], "owner_estimates"):
            if not isinstance(e, dict) or e.get("provenance", "owner_estimate") != "owner_estimate":
                raise CaseError("an owner estimate is always labelled owner_estimate, never verified")
            amt = e.get("amount_usd")
            if amt is not None and (isinstance(amt, bool) or not isinstance(amt, (int, float)) or amt != amt or amt in (float("inf"), float("-inf"))):
                raise CaseError("amount_usd must be a finite number or absent")
            out["owner_estimates"].append({"label": _s(e.get("label"), "estimate label"), "amount_usd": amt, "note": _s(e.get("note"), "estimate note", False),
                                           "provenance": "owner_estimate"})
    for k in ("alternatives_considered", "uncertainty", "missing_evidence", "category_tags"):
        if k in c:
            out[k] = [_s(x, k) for x in _list(c[k], k)]
    if "outcome" in c:
        if c["outcome"] not in (None, ""):
            raise CaseError("an outcome is recorded later with the `outcome` command, not at import")
    return out


# ---------------------------------------------------------------- the append-only chain
def rows() -> list[dict]:
    p = _log()
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def verify() -> tuple[bool, str]:
    prev = GENESIS
    for n, r in enumerate(rows(), 1):
        body = {k: v for k, v in r.items() if k != "row_hash"}
        if r.get("seq") != n or r.get("prev_hash") != prev or r.get("row_hash") != sha256_of(body):
            return False, f"chain broken at row {n}"
        prev = r["row_hash"]
    return True, f"{len(rows())} rows, chain ok"


def _append(kind: str, listing_id: Optional[str], body: dict, entered_by: str, why: str = "") -> dict:
    d = store_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    _must_be_private(d, "the case store")
    ok, msg = verify()
    if not ok:
        raise CaseError("refusing to append to a broken chain: " + msg)
    cur = rows()
    r = {"seq": len(cur) + 1, "prev_hash": cur[-1]["row_hash"] if cur else GENESIS, "kind": kind, "listing_id": listing_id, "entered_by": entered_by,
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
    if any(_case_row(c["listing_id"], c["source"]) for c in cases):
        raise CaseError("a case for that listing already exists: use `correct`, history is never overwritten")
    return [_append("case", c["listing_id"], c, entered_by) for c in cases]


def _case_row(listing_id: str, source: Optional[str] = None) -> Optional[dict]:
    hits = [r for r in rows() if r["kind"] == "case" and r["listing_id"] == listing_id and (source is None or r["body"]["source"] == source)]
    return hits[0] if hits else None


def correct(listing_id: str, patch: dict, why: str, entered_by: str = "michael") -> dict:
    if not _case_row(listing_id):
        raise CaseError("no case for that listing")
    p = validate_case(patch, partial=True)
    p.pop("listing_id", None)
    if not p or not why.strip():
        raise CaseError("a correction needs changed fields and a reason")
    return _append("correction", listing_id, p, entered_by, why)


def outcome(listing_id: str, text: str, entered_by: str = "michael") -> dict:
    if not _case_row(listing_id):
        raise CaseError("no case for that listing")
    return _append("outcome", listing_id, {"text": _s(text, "outcome text"), "label": "owner_reported_actual"}, entered_by)


def reset(listing_id: str, why: str, entered_by: str = "michael") -> dict:
    if not _case_row(listing_id) or not why.strip():
        raise CaseError("a reset needs an existing case and a reason")
    return _append("reset", listing_id, {}, entered_by, why)


def set_enabled(on: bool, why: str, entered_by: str = "michael") -> dict:
    if not why.strip():
        raise CaseError("a reason is required")
    return _append("enable" if on else "disable", None, {}, entered_by, why)


def learning_enabled() -> bool:
    state = True
    for r in rows():
        if r["kind"] in ("enable", "disable"):
            state = r["kind"] == "enable"
    return state


def effective(listing_id: str) -> Optional[dict]:
    """The case with corrections applied in order, its outcomes (owner-reported, separate from estimates) and history; None if there is none."""
    first = _case_row(listing_id)
    if not first:
        return None
    view, hist, outs, active = dict(first["body"]), [], [], True
    for r in rows():
        if r["listing_id"] != listing_id or r["seq"] == first["seq"]:
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
    it never turns a pass into a category dislike, never changes a filter or gate, and never produces a bid amount."""
    if not isinstance(candidate, dict) or not candidate.get("listing_id"):
        raise CaseError("the candidate needs a listing_id")
    base = {"status": "PROPOSAL_FOR_OWNER_REVIEW", "candidate": {k: candidate.get(k) for k in ("listing_id", "source", "title")},
            "authority": "A precedent for the owner to review. Not a bid, purchase, contact or filter override; hard filters and evidence gates still apply.", "matches": []}
    if not learning_enabled():
        return {**base, "note": "learned use is DISABLED by the owner; nothing applied"}
    cterms = _terms(candidate.get("title"), candidate.get("text"), *(candidate.get("category_tags") or []))
    have_kinds = {e.get("kind") for e in candidate.get("evidence") or []}
    for r in rows():
        if r["kind"] != "case" or r["listing_id"] == candidate["listing_id"]:
            continue
        eff = effective(r["listing_id"])
        if not eff or not eff["active"]:
            continue
        c = eff["case"]
        shared = cterms & _terms(c.get("title"), *(c.get("category_tags") or []))
        if len(shared) < min_shared:
            continue
        base["matches"].append({
            "source_case": {"listing_id": c["listing_id"], "source": c["source"], "decided_at": c["decided_at"], "case_row": eff["first_seq"], "corrections": len([h for h in eff["history"] if h["kind"] == "correction"])},
            "similarity": {"shared_terms": sorted(shared), "score": round(len(shared) / max(1, len(cterms | _terms(c.get("title"), *(c.get("category_tags") or [])))), 3)},
            "precedent_decision": c["decision"], "precedent_scope": "this one listing only; not a category preference",
            "reason_summary": c["reason_summary"],
            "verified_facts": [e for e in c["evidence"] if e["provenance"] == "verified"],
            "unverified_evidence": [e for e in c["evidence"] if e["provenance"] == "unverified"],
            "owner_estimates_not_facts": c.get("owner_estimates", []),
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
    why = rest[rest.index("--why") + 1] if "--why" in rest else ""
    pos = [x for i, x in enumerate(rest) if x != "--why" and (i == 0 or rest[i - 1] != "--why")]
    try:
        if cmd == "template":
            print(json.dumps(TEMPLATE, indent=1))
        elif cmd == "import":
            for r in import_cases(Path(pos[0])):
                print(f"imported listing {r['listing_id']} as row {r['seq']} {r['row_hash'][:19]}")
        elif cmd == "show":
            e = effective(pos[0])
            print(json.dumps(e, indent=1) if e else "no case for that listing")
            return 0 if e else 1
        elif cmd == "correct":
            print("correction row", correct(pos[0], json.loads(Path(pos[1]).read_text()), why)["seq"])
        elif cmd == "outcome":
            print("outcome row", outcome(pos[0], pos[1])["seq"])
        elif cmd == "reset":
            print("reset row", reset(pos[0], why)["seq"])
        elif cmd in ("disable", "enable"):
            print(cmd, "row", set_enabled(cmd == "enable", why)["seq"])
        elif cmd == "verify":
            ok, msg = verify()
            print(msg)
            return 0 if ok else 1
        elif cmd == "propose":
            print(json.dumps(propose(json.loads(Path(pos[0]).read_text())), indent=1))
        else:
            print(__doc__)
            return 2
    except (CaseError, OSError, ValueError, IndexError) as e:
        print("REFUSED:", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
