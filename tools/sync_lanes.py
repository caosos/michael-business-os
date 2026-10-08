"""Install lanes 02 (mbos-discovery), 03 (mbos-economics) and 05 (mbos-governance) from their PUSHED heads into .venv, so the gate's
"installed == pushed" check compares like with like. Never uses a lane's working tree or a stale build/ directory.

    .venv/bin/python -I tools/sync_lanes.py
"""

import subprocess
import sys
import tempfile
import tarfile
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UV = ROOT / ".tools" / "uv"
PY = ROOT / ".venv" / "bin" / "python"
LANES = [("mbos-economics", "origin/research/agent-03-economics", "economics"), ("mbos-governance", "origin/research/agent-05-governance", ""),
         ("mbos-discovery", "origin/research/agent-02-opportunity", "")]


def main() -> int:
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=ROOT, check=True)
    for pkg, ref, sub in LANES:
        args = ["git", "archive", ref] + ([sub] if sub else [])
        tar = subprocess.run(args, cwd=ROOT, capture_output=True, check=True).stdout
        with tempfile.TemporaryDirectory(prefix="mbos-sync-") as d:
            tarfile.open(fileobj=io.BytesIO(tar)).extractall(d, filter="data")
            root = Path(d) / sub if sub else Path(d)
            for b in root.glob("build"):
                import shutil
                shutil.rmtree(b)
            r = subprocess.run([str(UV), "pip", "install", "--python", str(PY), "--reinstall-package", pkg, str(root)], capture_output=True, text=True)
            print(f"{pkg} <- {ref} @ {subprocess.run(['git','rev-parse','--short',ref],cwd=ROOT,capture_output=True,text=True).stdout.strip()}: "
                  f"{'ok' if r.returncode == 0 else 'FAILED ' + r.stderr[-200:]}")
            if r.returncode:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
