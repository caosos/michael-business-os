"""Cross-lane interoperability against the peers' ACTUAL code on their pushed branches (read-only).

Since ADR-0010 the yardstick is the normative `contracts/canonical/vectors.json`: 10 canonical vectors,
6 rejections and a 2-receipt chain. For every lane:
  * payload hash: the lane's own function runs on every vector (MBOS-CJSON-1 → `sha256:`) and every rejection
  * row hash:     the lane's own receipt-hash function (where it has a ledger or stand-in) re-derives the chain (MBOS-RH-1)
  * SQL twins:    each PostgreSQL implementation present (pinned reference, 01 spine, 04 state) runs the same
                  vectors on a throwaway local PostgreSQL 16
plus contract-pin consistency, peer-output conformance and single-ledger ownership.

Each lane is probed in its own subprocess over a `git archive` of its branch head, so its package imports
resolve normally and lanes never share module state. Nothing is written to any other branch or worktree.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

from .contracts import CONTRACTS_DIR, Contracts

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
VECTORS = CONTRACTS_DIR / "canonical" / "vectors.json"
REF_SQL = CONTRACTS_DIR / "canonical" / "mbos_canonical.sql"
PROBE = pathlib.Path(__file__).resolve().parent / "_probe.py"
LANES = {
    "01": "research/agent-01-coordinator", "02": "research/agent-02-opportunity",
    "03": "research/agent-03-economics", "04": "research/agent-04-state",
    "05": "research/agent-05-governance", "06": "research/agent-06-communications",
    "07": "research/agent-07-marketing",
}
# lane → (source root inside the archive, probe spec). 04 has no Python hasher: its hashing is SQL (see SQL twins).
PROBES = {
    "01": ("src", {"payload": "mbos.hashing:sha256_of", "row": None}),
    "02": ("src", {"payload": "mbos_discovery.ids:canonical_json|mbos_discovery.ids:sha256_ref", "row": None}),
    "03": ("economics/src", {"payload": "mbos_economics.canonical:content_hash", "row": None}),
    "05": ("src", {"payload": "mbos_governance.ids:payload_hash", "row": "mbos_governance.store:compute_row_hash"}),
    "06": (".", {"payload": "operator_ui.util:sha256_of", "row": "operator_ui.store:row_hash_of"}),
    "07": ("qa", {"payload": "mbos_qa.core:sha256_ref", "row": "mbos_qa.core:receipt_row_hash"}),
}


def _git(*args, binary=False):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode()


def _tag(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass
class Check:
    group: str
    name: str
    status: str  # PASS | FAIL | PENDING | UNKNOWN | INFO | RULED-PENDING
    detail: str = ""


@dataclass
class InteropReport:
    refs: dict = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    lanes: dict = field(default_factory=dict)  # lane → probe output
    sql: dict = field(default_factory=dict)    # implementation → result

    def add(self, *a):
        self.checks.append(Check(*a))


# ------------------------------------------------------------------ 1 pins
def check_pins(rep: InteropReport) -> None:
    pin = json.loads((CONTRACTS_DIR / "PIN.json").read_text())
    by_name: dict[str, set] = {}
    for rel, h in pin["files"].items():
        by_name.setdefault(rel.split("/")[-1], set()).add(h)
    pinned_ids = {json.loads((CONTRACTS_DIR / rel).read_text()).get("$id")
                  for rel in pin["files"] if rel.endswith(".schema.json")}
    for lane, br in LANES.items():
        if lane == "07":
            continue
        ref = f"origin/{br}"
        # README.md is a generic name: only the pinned canonical/README.md counts, matched by path
        files = [f for f in _git("ls-tree", "-r", "--name-only", ref).split()
                 if f.split("/")[-1] in by_name and not f.startswith("docs/research/contracts/")
                 and (f.split("/")[-1] != "README.md" or f.endswith("canonical/README.md"))]
        same, differ, same_id = 0, [], []
        for f in files:
            blob = _git("show", f"{ref}:{f}", binary=True)
            if _tag(blob) in by_name[f.split("/")[-1]]:
                same += 1
                continue
            differ.append(f)
            try:
                if json.loads(blob).get("$id") in pinned_ids:
                    same_id.append(f)
            except ValueError:
                pass
        if not files:
            rep.add("1 contract pins", f"lane {lane}: vendored copies", "INFO", "none vendored (reads the coordinator path)")
            continue
        rep.add("1 contract pins", f"lane {lane}: vendored copies byte-identical to pin",
                "PASS" if not differ else "FAIL", f"{same} identical" + (f"; differ: {differ}" if differ else ""))
        if same_id:
            rep.add("1 contract pins", f"lane {lane}: changed schema keeps the pinned $id", "FAIL",
                    f"{same_id}: ADR-0004 requires a new $id when a vendored schema changes (queued as C-03)")


# ------------------------------------------------------------------ 2 peer outputs
def check_peer_outputs(rep: InteropReport) -> None:
    c = Contracts()
    ref = f"origin/{LANES['03']}"
    files = [f for f in _git("ls-tree", "-r", "--name-only", ref).split() if f.endswith(".scored.json")]
    bad, n = [], 0
    for f in files:
        d = json.loads(_git("show", f"{ref}:{f}"))
        prov = d.get("provenance") or []
        for kind, doc in [("item", d["item"])] + [("provenance", p) for p in (prov if isinstance(prov, list) else [prov])]:
            n += 1
            if c.errors(kind, doc):
                bad.append(f"{f.split('/')[-1]}:{kind}")
    rep.add("2 peer outputs", f"lane 03: {len(files)} scored examples validate against frozen Item/Provenance v1",
            "PASS" if not bad else "FAIL", f"{n} documents" + (f"; invalid: {bad}" if bad else ""))


# ------------------------------------------------------------------ 3 lane hashers on vectors.json
def _archive(lane: str, dest: pathlib.Path) -> pathlib.Path:
    if lane == "07":  # this lane: the committed HEAD of this worktree (identical to what is pushed after commit)
        commit = _git("rev-parse", "HEAD").strip()
    else:
        commit = _git("rev-parse", f"origin/{LANES[lane]}").strip()
    d = dest / f"lane{lane}"
    d.mkdir(parents=True)
    subprocess.run(["tar", "-x", "-C", str(d)], input=_git("archive", commit, binary=True), check=True)
    return d


def check_lane_hashers(rep: InteropReport, scratch: pathlib.Path) -> None:
    vec = json.loads(VECTORS.read_text())
    n_c, n_r = len(vec["cjson"]), len(vec["reject"])
    for lane, (sub, spec) in PROBES.items():
        root = _archive(lane, scratch) / sub
        mod_file = root / (spec["payload"].split(":")[0].replace(".", "/") + ".py")
        if not mod_file.exists():
            rep.lanes[lane] = {"absent": True}
            rep.add("3 lane hashers (vectors.json)", f"lane {lane}: payload hash", "INFO",
                    f"no own hasher at head (`{mod_file.relative_to(root)}` removed); the lane hashes through "
                    "Agent 01's spine, which is covered by row 01")
            continue
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
        p = subprocess.run([sys.executable, str(PROBE), str(root), str(VECTORS), json.dumps(spec)],
                           capture_output=True, text=True, env=env, cwd=root, timeout=120)
        try:
            out = json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            out = {"load_error": (p.stderr.strip().splitlines() or ["no output"])[-1]}
        rep.lanes[lane] = out
        if out.get("load_error"):
            rep.add("3 lane hashers (vectors.json)", f"lane {lane}: payload hash", "UNKNOWN", out["load_error"])
            continue
        ok_c = sum(c["ok"] for c in out["cjson"])
        ok_r = sum(r["ok"] for r in out["reject"])
        bad = [c["name"] for c in out["cjson"] if not c["ok"]] + [f"reject:{r['name']}" for r in out["reject"] if not r["ok"]]
        rep.add("3 lane hashers (vectors.json)", f"lane {lane}: payload hash = MBOS-CJSON-1",
                "PASS" if not bad else "FAIL", f"{ok_c}/{n_c} vectors, {ok_r}/{n_r} rejections"
                + (f"; failing: {', '.join(bad)}" if bad else ""))
        if out.get("chain") is not None:
            rep.add("3 lane hashers (vectors.json)", f"lane {lane}: receipt row_hash = MBOS-RH-1 (vectors receipt_chain)",
                    "PASS" if out["chain"]["ok"] else "FAIL", out["chain"]["detail"])


# ------------------------------------------------------------------ 4 SQL twins on PostgreSQL
def _sql_sources() -> dict[str, str | None]:
    src = {"ADR-0010 reference SQL (pinned)": REF_SQL.read_text()}
    for lane in ("01", "04"):
        ref = f"origin/{LANES[lane]}"
        files = [f for f in _git("ls-tree", "-r", "--name-only", ref).split() if f.endswith(".sql")]
        hit = [f for f in files if "FUNCTION mbos.cjson(" in _git("show", f"{ref}:{f}")]
        label = f"lane {lane} SQL ({hit[0].split('/')[-1]})" if hit else f"lane {lane} SQL"
        src[label] = _git("show", f"{ref}:{hit[0]}") if hit else None
    return src


def check_sql_twins(rep: InteropReport) -> None:
    try:
        import pgserver  # noqa: PLC0415
        import psycopg  # noqa: PLC0415
    except ImportError:
        rep.add("4 SQL twins (PostgreSQL)", "SQL implementations", "UNKNOWN", "pgserver/psycopg not installed")
        return
    vec = json.loads(VECTORS.read_text())
    root = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "a07-interop-pg"
    srv = pgserver.get_server(str(root), cleanup_mode="stop")
    base = srv.get_uri()
    for i, (label, sql) in enumerate(_sql_sources().items()):
        if sql is None:
            status = "PENDING" if label.startswith("lane 04") else "INFO"
            rep.add("4 SQL twins (PostgreSQL)", f"{label}: MBOS-CJSON-1 / MBOS-RH-1", status,
                    "no `mbos.cjson` function on the branch yet (D-02 is CLAIMED by 04)" if status == "PENDING"
                    else "no SQL twin on the branch")
            continue
        db = f"a07_twin_{i}"
        with psycopg.connect(base, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {db}")
            c.execute(f"CREATE DATABASE {db}")
        head, _, query = base.partition("?")
        uri = head.rsplit("/", 1)[0] + f"/{db}" + (f"?{query}" if query else "")
        res = {"cjson": 0, "reject": 0, "chain": None, "fail": []}
        with psycopg.connect(uri, autocommit=True) as c:
            c.execute(sql)
            for case in vec["cjson"]:
                canon, h = c.execute("SELECT mbos.cjson(%s::jsonb), mbos.cjson_sha256(%s::jsonb)",
                                     (case["input"], case["input"])).fetchone()
                if canon == case["canonical"] and h == case["sha256"]:
                    res["cjson"] += 1
                else:
                    res["fail"].append(case["name"])
            for case in vec["reject"]:
                try:
                    c.execute("SELECT mbos.cjson(%s::jsonb)", (case["input"],)).fetchone()
                    res["fail"].append("reject:" + case["name"])
                except psycopg.Error:
                    res["reject"] += 1
            has_rh = c.execute("SELECT to_regproc('mbos.rh1_row_hash') IS NOT NULL").fetchone()[0]
            if has_rh:
                bad = [r["seq"] for r in vec["receipt_chain"]
                       if c.execute("SELECT mbos.rh1_row_hash(%s::jsonb)", (json.dumps(r),)).fetchone()[0] != r["row_hash"]]
                res["chain"] = not bad
                if bad:
                    res["fail"].append(f"chain seq {bad}")
        with psycopg.connect(base, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {db}")
        rep.sql[label] = res
        rep.add("4 SQL twins (PostgreSQL)", f"{label}: MBOS-CJSON-1" + (" + MBOS-RH-1" if res["chain"] is not None else ""),
                "PASS" if not res["fail"] else "FAIL",
                f"{res['cjson']}/{len(vec['cjson'])} vectors, {res['reject']}/{len(vec['reject'])} rejections"
                + (", chain verified" if res["chain"] else "") + (f"; failing: {res['fail']}" if res["fail"] else ""))


# ------------------------------------------------------------------ 5 ownership / ledger conformance
def check_ledger(rep: InteropReport) -> None:
    owners, cjson_rowhash = [], {}
    for lane in ("01", "04"):
        ref = f"origin/{LANES[lane]}"
        sql = {f: _git("show", f"{ref}:{f}") for f in _git("ls-tree", "-r", "--name-only", ref).split() if f.endswith(".sql")}
        if any("CREATE TABLE mbos.receipts" in t or "CREATE TABLE IF NOT EXISTS mbos.receipts" in t for t in sql.values()):
            owners.append(lane)
        cjson_rowhash[lane] = any("row_hash" in t and "mbos.cjson" in t for t in sql.values())
    rep.add("5 ledger", "single receipts ledger (ADR-0010: Agent 04 sole owner)",
            "PASS" if owners == ["04"] else "RULED-PENDING",
            f"`mbos.receipts` defined by lanes {owners}. 01's DDL is a reference spine until A-01 phase 2.")
    rep.add("5 ledger", "lane 04 ledger computes row_hash with MBOS-CJSON-1 (D-02)",
            "PASS" if cjson_rowhash["04"] else "PENDING",
            "found in 04 migrations" if cjson_rowhash["04"] else
            "04 @ head still hashes `jsonb::text` (`0001_foundation.sql`); D-02 is CLAIMED by 04")


def run(fetch: bool = False) -> InteropReport:
    if fetch:
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=REPO, check=False)
    rep = InteropReport(refs={lane: _git("rev-parse", "--short", "HEAD" if lane == "07" else f"origin/{br}").strip()
                              for lane, br in LANES.items()})
    with tempfile.TemporaryDirectory() as td:
        check_pins(rep)
        check_peer_outputs(rep)
        check_lane_hashers(rep, pathlib.Path(td))
        check_sql_twins(rep)
        check_ledger(rep)
    return rep


def verdicts(rep: InteropReport) -> dict[str, str]:
    """F-13 / F-14 status from the evidence (G-01 acceptance: closed or re-opened with evidence)."""
    py = {c.name.split(":")[0]: c.status for c in rep.checks if c.group.startswith("3") and "payload" in c.name}
    rh = {c.name.split(":")[0]: c.status for c in rep.checks if c.group.startswith("3") and "row_hash" in c.name}
    sql = [c for c in rep.checks if c.group.startswith("4")]
    led = {c.name: c.status for c in rep.checks if c.group.startswith("5")}
    f14_open = sorted(k for k, v in py.items() if v not in ("PASS", "INFO")) + sorted(c.name.split(":")[0] for c in sql if c.status != "PASS")
    f13_open = sorted(k for k, v in rh.items() if v != "PASS") + [k for k, v in led.items() if v != "PASS"]
    return {
        "F-14": "CLOSED: every lane hasher and SQL twin matches vectors.json" if not f14_open else
                "RULED (ADR-0010), conformance OPEN for: " + "; ".join(f14_open),
        "F-13": "CLOSED: one ledger, MBOS-RH-1 everywhere" if not f13_open else
                "RULED (ADR-0010), conformance OPEN for: " + "; ".join(f13_open),
    }


def render(rep: InteropReport) -> str:
    vec = json.loads(VECTORS.read_text())
    v = verdicts(rep)
    L = ["# Cross-lane interoperability report: ADR-0010 conformance (lane G, task G-01)", "",
         "> Generated by `python -m mbos_qa interop`. It runs each lane's **own** hashing code from a `git archive` "
         "of its pushed head, one subprocess per lane, against the normative `contracts/canonical/vectors.json`. "
         "Every PostgreSQL implementation present runs the same vectors on a throwaway PostgreSQL 16. "
         "Nothing was written to any other branch or worktree.", "",
         "Heads: " + ", ".join(f"{k} `{h}`" for k, h in rep.refs.items()), "",
         f"- **F-14 (number canonicalisation):** {v['F-14']}",
         f"- **F-13 (one ledger, one row_hash):** {v['F-13']}", "",
         "## Lane × vector matrix (✔ = the lane's own function reproduces the vector's sha256 / rejects the input)", ""]
    lanes = [x for x in rep.lanes if not rep.lanes[x].get("absent")]
    L += ["| Vector | " + " | ".join(f"{x}" for x in lanes) + " | " + " | ".join(rep.sql) + " |",
          "|---|" + "---|" * (len(lanes) + len(rep.sql))]

    def cell(out, kind, name):
        if out.get("load_error"):
            return "?"
        for c in out.get(kind, []):
            if c["name"] == name:
                if c["ok"]:
                    return "✔"
                got = str(c["got"])
                return "✘ " + ("raised" if got.startswith("RAISED") else got[7:15] if got.startswith("sha256:") else got)
        return "—"

    for case in vec["cjson"]:
        sqlc = ["✔" if case["name"] not in r["fail"] else "✘" for r in rep.sql.values()]
        L.append(f"| {case['name']} | " + " | ".join(cell(rep.lanes[x], "cjson", case["name"]) for x in lanes)
                 + " | " + " | ".join(sqlc) + " |")
    for case in vec["reject"]:
        sqlc = ["✔" if "reject:" + case["name"] not in r["fail"] else "✘" for r in rep.sql.values()]
        L.append(f"| reject: {case['name']} | " + " | ".join(cell(rep.lanes[x], "reject", case["name"]) for x in lanes)
                 + " | " + " | ".join(sqlc) + " |")
    chain_row = []
    for x in lanes:
        ch = rep.lanes[x].get("chain")
        chain_row.append("—" if ch is None else ("✔" if ch["ok"] else "✘"))
    L.append("| receipt_chain (MBOS-RH-1) | " + " | ".join(chain_row) + " | "
             + " | ".join("—" if r["chain"] is None else ("✔" if r["chain"] else "✘") for r in rep.sql.values()) + " |")
    L += ["", "— = this lane has no such function (02/03 have no ledger; 01's ledger hashing is SQL). "
          "? = could not load. A ✘ with hex shows the first hex digits of the hash the lane produced.", "",
          "## All checks", "", "| Group | Check | Result | Detail |", "|---|---|---|---|"]
    L += [f"| {c.group} | {c.name} | **{c.status}** | {c.detail.replace('|', '/')} |" for c in rep.checks]
    L.append("")
    return "\n".join(L)
