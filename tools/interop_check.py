"""ADR-0010 cross-lane interoperability check (coordinator tool; read-only on peers).

For every lane, extracts its CURRENT hashing module from its pushed branch with `git show`, imports it in
isolation (stdlib-only modules), and runs it on docs/research/contracts/canonical/vectors.json.
Prints one conformance row per lane. Re-run after each lane conforms:

    .venv/bin/python -I tools/interop_check.py [--fetch]
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
VEC = json.loads((ROOT / "docs/research/contracts/canonical/vectors.json").read_text())

# lane, branch, module path, adapter -> f(obj) returning "sha256:<hex>" of the lane's payload hash
LANES = [
    ("01", "research/agent-01-coordinator", "docs/research/contracts/canonical/mbos_canonical.py", lambda m: m.sha256_of),
    ("02", "research/agent-02-opportunity", "src/mbos_discovery/ids.py", lambda m: lambda o: m.sha256_ref(m.canonical_json(o))),
    ("03", "research/agent-03-economics", "economics/src/mbos_economics/canonical.py", lambda m: m.content_hash),
    ("05", "research/agent-05-governance", "src/mbos_governance/ids.py", lambda m: m.payload_hash),
    ("06", "research/agent-06-communications", "operator_ui/util.py", lambda m: m.sha256_of),
    ("07", "research/agent-07-marketing", "qa/mbos_qa/core.py", lambda m: lambda o: m.sha256_ref(o)),
]


def load(branch: str, path: str, tmp: pathlib.Path):
    src = subprocess.run(["git", "show", f"origin/{branch}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if src.returncode:
        return None, "not found on branch"
    f = tmp / (branch.replace("/", "_") + ".py")
    f.write_text(src.stdout)
    spec = importlib.util.spec_from_file_location(f.stem, f)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # relative imports etc.
        return None, f"import failed: {type(e).__name__}: {e}"
    return mod, ""


def main() -> int:
    if "--fetch" in sys.argv:
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=ROOT)
    rows, all_ok = [], True
    with tempfile.TemporaryDirectory() as td:
        for lane, branch, path, adapt in LANES:
            head = subprocess.run(["git", "rev-parse", "--short", f"origin/{branch}"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
            mod, err = load(branch, path, pathlib.Path(td))
            if mod is None:
                rows.append((lane, head, "-", err)); all_ok = False; continue
            f = adapt(mod)
            ok, fails = 0, []
            for case in VEC["cjson"]:
                try:
                    got = f(json.loads(case["input"]))
                except Exception as e:
                    got = f"raised {type(e).__name__}"
                if got == case["sha256"]:
                    ok += 1
                else:
                    fails.append(case["name"])
            all_ok &= not fails
            rows.append((lane, head, f"{ok}/{len(VEC['cjson'])}", "CONFORMS" if not fails else "differs: " + "; ".join(fails)))
    print("| Lane | Head | CJSON vectors | Result |\n|---|---|---|---|")
    for r in rows:
        print(f"| {r[0]} | `{r[1]}` | {r[2]} | {r[3]} |")
    print("\nReceipt row_hash (MBOS-RH-1): checked by each lane's own test against vectors.json `receipt_chain`;"
          " Postgres ledgers additionally against mbos_canonical.sql.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
