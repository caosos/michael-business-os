"""Refuse to test the wrong code. pip keeps an old copy when the version string is unchanged ("0.1.0"), so a re-pin can
silently test stale code. This compares the INSTALLED package files, byte for byte, with the pinned commit's files."""
from __future__ import annotations

import hashlib
import importlib
import json
import pathlib
import subprocess

QA_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = QA_ROOT.parent
PINS = json.loads((QA_ROOT / "impl_lane_pins.json").read_text())


def _git_blob(ref: str, path: str) -> bytes | None:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def check(packages=("mbos", "mbos_governance")) -> list[str]:
    """Return mismatch descriptions (empty = installed code is exactly the pinned code)."""
    problems = []
    layout = {"mbos": (PINS["mbos_01"], "src/mbos"), "mbos_governance": (PINS["lane_e_05"], "src/mbos_governance")}
    for pkg in packages:
        ref, root = layout[pkg]
        try:
            mod = importlib.import_module(pkg)
        except ImportError as e:
            problems.append(f"{pkg}: not installed ({e})")
            continue
        base = pathlib.Path(mod.__file__).parent
        files = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, root], cwd=REPO, capture_output=True,
                               text=True).stdout.split()
        for f in files:
            if not f.endswith(".py"):
                continue
            rel = f[len(root) + 1:]
            want = _git_blob(ref, f)
            have = (base / rel).read_bytes() if (base / rel).exists() else None
            if have is None:
                problems.append(f"{pkg}/{rel}: missing from the install")
            elif hashlib.sha256(have).digest() != hashlib.sha256(want).digest():
                problems.append(f"{pkg}/{rel}: differs from {ref[:7]}")
    return problems


def require() -> None:
    bad = check()
    if bad:
        raise RuntimeError("installed packages do not match qa/impl_lane_pins.json (stale pip install?):\n  " + "\n  ".join(bad[:8])
                           + "\nre-install: git archive <pin> | tar -x -C DIR && pip install --force-reinstall --no-deps DIR")


def install_pins(workroot: str = "/tmp/a07pins") -> list[str]:
    """(Re)install mbos and mbos_governance from the pinned commits, then VERIFY byte identity. Always a fresh tree with
    no build/ or *.egg-info (a stale build dir made pip install old files under the same version string)."""
    import shutil
    import subprocess as sp
    import sys
    import tarfile
    import io

    out = []
    for pkg, ref in (("mbos", PINS["mbos_01"]), ("mbos_governance", PINS["lane_e_05"])):
        d = pathlib.Path(workroot) / pkg
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        tarfile.open(fileobj=io.BytesIO(sp.run(["git", "archive", ref], cwd=REPO, capture_output=True, check=True).stdout)).extractall(d, filter="data")
        shutil.rmtree(d / "build", ignore_errors=True)
        for e in d.glob("src/*.egg-info"):
            shutil.rmtree(e, ignore_errors=True)
        sp.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--no-cache-dir",
                "--force-reinstall", "--no-deps", str(d)], check=True, capture_output=True)
        out.append(f"{pkg} @ {ref[:7]}")
    importlib.invalidate_caches()
    return out
