"""Cross-lane interoperability checks against the peers' ACTUAL code on their branches (read-only).

Lane G's integration question is: can each lane verify what another lane wrote? This runs three
groups of checks:
  1. Contract pins. Every lane's vendored copy of the frozen contracts must be byte-identical to
     the pin, and any changed schema must carry a new `$id`.
  2. Peer outputs. Example documents a lane emits must validate against the frozen contracts.
  3. Hash agreement. Each lane's own canonical-JSON / sha256 function is run on shared test
     vectors, and each lane's row_hash formula is applied to one receipt.

Peer modules are extracted with `git show` into a scratch directory and only stdlib-only hashing
modules are imported. Postgres-side formulas run on a throwaway local PostgreSQL 16 (pgserver)
when it is available; otherwise they are reported as UNKNOWN.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
from dataclasses import dataclass, field

from .contracts import CONTRACTS_DIR, Contracts

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
LANES = {
    "01": "research/agent-01-coordinator", "02": "research/agent-02-opportunity",
    "03": "research/agent-03-economics", "04": "research/agent-04-state",
    "05": "research/agent-05-governance", "06": "research/agent-06-communications",
}

# (lane, path on branch, callable name, adapter) — adapter turns the module function into obj -> "sha256:…"
HASHERS = [
    ("01", "src/mbos/hashing.py", "sha256_of", lambda f: f),
    ("02", "src/mbos_discovery/ids.py", "canonical_json", lambda f: lambda o: _tag(f(o))),
    ("03", "economics/src/mbos_economics/canonical.py", "content_hash", lambda f: f),
    ("05", "src/mbos_governance/ids.py", "payload_hash", lambda f: f),
    ("06", "operator_ui/util.py", "sha256_of", lambda f: f),
]

VECTORS = {
    "ints + strings": {"offer": 850, "template_id": "seller_inquiry_v1", "to_ref": "relay:QA-1"},
    "integral float (850.0)": {"offer": 850.0, "to_ref": "relay:QA-1"},
    "decimal float (3.20)": {"fuel_price_per_gal": 3.20, "to_ref": "relay:QA-1"},
    "unicode + nested + bool/null": {"body": "Héllo — ok", "meta": {"b": True, "z": None, "list": [2, 1]}},
}

# Receipt row_hash formulas, cited to the source line that defines them.
ROW_HASH_FORMULAS = {
    "contract text / 05 / 06 / 07": "sha256(compact_sorted_json(row − row_hash) ‖ prev_hash)  "
                                    "[receipt.schema.json row_hash; 05 store.compute_row_hash; 06 store.row_hash_of]",
    "04 state (Postgres)": "sha256(jsonb::text(row − row_hash, prev_hash included))  "
                           "[agent-04 state/migrations/0001_foundation.sql receipt_canonical + receipts_before_insert]",
    "01 spine (Postgres)": "sha256(seq ‖ '|' ‖ jsonb::text(body − seq/prev_hash/row_hash) ‖ '|' ‖ prev_hash)  "
                           "[agent-01 src/mbos/db/migrations/0001_spine.sql mbos.receipt_row_hash]",
}


def _tag(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _git(*args, binary=False):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode()


@dataclass
class Check:
    group: str
    name: str
    status: str  # PASS | FAIL | UNKNOWN | INFO
    detail: str = ""
    tag: str = "FACT"


@dataclass
class InteropReport:
    refs: dict = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    hash_matrix: dict = field(default_factory=dict)
    row_hashes: dict = field(default_factory=dict)

    def add(self, *a, **k):
        self.checks.append(Check(*a, **k))


def check_pins(rep: InteropReport) -> None:
    pin = json.loads((CONTRACTS_DIR / "PIN.json").read_text())
    by_name: dict[str, set] = {}
    for rel, h in pin["files"].items():
        by_name.setdefault(rel.split("/")[-1], set()).add(h)
    pinned_ids = {json.loads((CONTRACTS_DIR / rel).read_text()).get("$id"): h
                  for rel, h in pin["files"].items() if rel.endswith(".schema.json")}
    for lane, br in LANES.items():
        ref = f"origin/{br}"
        files = [f for f in _git("ls-tree", "-r", "--name-only", ref).split()
                 if f.split("/")[-1] in by_name and not f.startswith("docs/research/contracts/")]
        same, differ, same_id = 0, [], []
        for f in files:
            blob = _git("show", f"{ref}:{f}", binary=True)
            h = _tag(blob)
            if h in by_name[f.split("/")[-1]]:
                same += 1
                continue
            differ.append(f)
            try:
                sid = json.loads(blob).get("$id")
            except ValueError:
                sid = None
            if sid in pinned_ids:
                same_id.append(f)
        if not files:
            rep.add("1 contract pins", f"lane {lane}: vendored copies", "INFO", "no vendored copies (reads coordinator path)")
            continue
        rep.add("1 contract pins", f"lane {lane}: vendored copies byte-identical to pin",
                "PASS" if not differ else "FAIL", f"{same} identical" + (f"; differ: {differ}" if differ else ""))
        if same_id:
            rep.add("1 contract pins", f"lane {lane}: changed schema keeps the pinned $id", "FAIL",
                    f"{same_id} — ADR-0004 requires a new $id/version when a vendored schema changes")


def check_peer_outputs(rep: InteropReport, scratch: pathlib.Path) -> None:
    c = Contracts()
    ref = f"origin/{LANES['03']}"
    files = [f for f in _git("ls-tree", "-r", "--name-only", ref).split() if f.endswith(".scored.json")]
    bad, n = [], 0
    for f in files:
        d = json.loads(_git("show", f"{ref}:{f}"))
        prov = d.get("provenance") or []
        docs = [("item", d["item"])] + [("provenance", p) for p in (prov if isinstance(prov, list) else [prov])]
        for kind, doc in docs:
            n += 1
            if c.errors(kind, doc):
                bad.append(f"{f.split('/')[-1]}:{kind}")
    rep.add("2 peer outputs", f"lane 03: {len(files)} scored examples validate against frozen Item/Provenance v1",
            "PASS" if not bad else "FAIL", f"{n} documents" + (f"; invalid: {bad}" if bad else ""))


def _load_peer(lane: str, path: str, scratch: pathlib.Path):
    src = _git("show", f"origin/{LANES[lane]}:{path}")
    d = scratch / f"lane{lane}"
    d.mkdir(parents=True, exist_ok=True)
    f = d / pathlib.Path(path).name
    f.write_text(src)
    spec = importlib.util.spec_from_file_location(f"peer{lane}_{f.stem}", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_payload_hashes(rep: InteropReport, scratch: pathlib.Path) -> None:
    from .core import sha256_ref
    fns = {"07": sha256_ref}
    for lane, path, name, adapt in HASHERS:
        try:
            fns[lane] = adapt(getattr(_load_peer(lane, path, scratch), name))
        except Exception as e:  # noqa: BLE001
            rep.add("3 hash agreement", f"lane {lane}: load {path}", "UNKNOWN", f"{type(e).__name__}: {e}", "UNKNOWN")
    for vname, vec in VECTORS.items():
        row = {}
        for lane, fn in sorted(fns.items()):
            try:
                row[lane] = fn(json.loads(json.dumps(vec)))
            except Exception as e:  # noqa: BLE001
                row[lane] = f"REFUSED ({type(e).__name__})"
        rep.hash_matrix[vname] = row
        hashes = {v for v in row.values() if v.startswith("sha256:")}
        refused = [k for k, v in row.items() if not v.startswith("sha256:")]
        if len(hashes) == 1:
            rep.add("3 hash agreement", f"payload hash agrees across lanes: {vname}", "PASS",
                    f"{len(row) - len(refused)} lanes agree" + (f"; refused by {refused}" if refused else ""))
        else:
            groups = {}
            for lane, h in row.items():
                groups.setdefault(h[:19] if h.startswith("sha256:") else h, []).append(lane)
            rep.add("3 hash agreement", f"payload hash agrees across lanes: {vname}", "FAIL",
                    "; ".join(f"{'+'.join(v)} → {k}" for k, v in groups.items()))


def _receipt_vector() -> tuple[dict, str]:
    prev = "sha256:" + "a" * 64
    row = {"receipt_id": "rcpt_01M4B3R6G0000000000000000A", "seq": 2, "ts": "2026-10-07T12:00:00Z",
           "schema_version": "1.0.0", "type": "ITEM_STATE_CHANGED", "actor": {"type": "agent", "id": "agent-07"},
           "intent": "interop vector — Héllo", "provenance_ids": ["prov_01M4B3R6G0000000000000000A"],
           "idempotency_key": "interop-1", "before_state": {"state": "NORMALIZED"},
           "after_state": {"state": "RESEARCHING"}, "prev_hash": prev}
    return row, prev


def check_row_hashes(rep: InteropReport) -> None:
    row, prev = _receipt_vector()
    compact = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    rep.row_hashes["contract text / 05 / 06 / 07"] = _tag(compact + prev)
    pg = _pg_jsonb_text([row, {k: v for k, v in row.items() if k not in ("seq", "prev_hash")}])
    if pg is None:
        rep.row_hashes["04 state (Postgres)"] = "UNKNOWN (no local PostgreSQL)"
        rep.row_hashes["01 spine (Postgres)"] = "UNKNOWN (no local PostgreSQL)"
    else:
        rep.row_hashes["04 state (Postgres)"] = _tag(pg[0])
        rep.row_hashes["01 spine (Postgres)"] = _tag(f"{row['seq']}|{pg[1]}|{prev}")
    vals = set(rep.row_hashes.values())
    status = "UNKNOWN" if pg is None else ("PASS" if len(vals) == 1 else "FAIL")
    rep.add("3 hash agreement", "receipt row_hash formula agrees across ledgers (01 spine, 04 state, contract)", status,
            "; ".join(f"{k} → {v[:19]}…" for k, v in rep.row_hashes.items()), "UNKNOWN" if pg is None else "FACT")
    if pg is not None:
        rep.add("3 hash agreement", "Postgres jsonb::text equals the Python canonical form", "FAIL" if pg[0] != compact else "PASS",
                f"jsonb: {pg[0][:70]}… vs python: {compact[:70]}…")


def _pg_jsonb_text(docs: list[dict]) -> list[str] | None:
    try:
        import pgserver  # noqa: PLC0415
    except ImportError:
        return None
    root = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "a07-interop-pg"
    srv = pgserver.get_server(str(root), cleanup_mode="stop")
    out = []
    for d in docs:
        res = srv.psql(f"SELECT ($json${json.dumps(d, ensure_ascii=False)}$json$)::jsonb::text;")
        out.append(res.strip().splitlines()[2].strip())
    return out


def check_ledger_ownership(rep: InteropReport) -> None:
    owners = []
    for lane in ("01", "04"):
        ref = f"origin/{LANES[lane]}"
        sql = [f for f in _git("ls-tree", "-r", "--name-only", ref).split() if f.endswith(".sql")]
        if any("CREATE TABLE mbos.receipts" in _git("show", f"{ref}:{f}") or
               "CREATE TABLE IF NOT EXISTS mbos.receipts" in _git("show", f"{ref}:{f}") for f in sql):
            owners.append(lane)
    rep.add("4 ownership", "exactly one lane defines the receipts ledger (`mbos.receipts`)",
            "PASS" if len(owners) == 1 else "FAIL",
            f"defined by lanes {owners}; ownership map (integration §5) assigns DDL/ledger to 04")


def run(fetch: bool = False) -> InteropReport:
    if fetch:
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=REPO, check=False)
    rep = InteropReport(refs={lane: _git("rev-parse", "--short", f"origin/{br}").strip() for lane, br in LANES.items()})
    with tempfile.TemporaryDirectory() as td:
        scratch = pathlib.Path(td)
        check_pins(rep)
        check_peer_outputs(rep, scratch)
        check_payload_hashes(rep, scratch)
        check_row_hashes(rep)
        check_ledger_ownership(rep)
    return rep


def render(rep: InteropReport) -> str:
    L = ["# Cross-lane interoperability report (lane G)", "",
         "> Generated by `python -m mbos_qa interop`. Runs the peers' **actual** hashing code (extracted read-only "
         "from their branches) and PostgreSQL 16 for the Postgres-side formulas. Nothing was modified on any other "
         "branch.", "",
         "Peer refs checked: " + ", ".join(f"{k} `{v}`" for k, v in rep.refs.items()), "",
         "| Group | Check | Result | Detail |", "|---|---|---|---|"]
    L += [f"| {c.group} | {c.name} | **{c.status}** | {c.detail.replace('|', '/')} |" for c in rep.checks]
    lanes = sorted({lane for row in rep.hash_matrix.values() for lane in row})
    L += ["", "## Payload-hash matrix (same input, each lane's own function)", "",
          "| Vector | " + " | ".join(f"lane {x}" for x in lanes) + " |", "|---|" + "---|" * len(lanes)]
    for v, row in rep.hash_matrix.items():
        L.append(f"| {v} | " + " | ".join(f"`{row.get(x, '—')[7:17]}`" if row.get(x, "").startswith("sha256:")
                                           else row.get(x, "—") for x in lanes) + " |")
    L += ["", "## Receipt row_hash formulas (one identical receipt)", "", "| Ledger | Formula | row_hash |", "|---|---|---|"]
    L += [f"| {k} | {ROW_HASH_FORMULAS[k].replace('|', chr(92) + '|')} | `{v[:23]}…` |" for k, v in rep.row_hashes.items()]
    L.append("")
    return "\n".join(L)
