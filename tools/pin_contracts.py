"""Pin the FROZEN contract bytes (07 F-46). The release gate fails if any pinned file changes.

    .venv/bin/python -I tools/pin_contracts.py --write     # only after an accepted ADR / semver bump
    .venv/bin/python -I tools/pin_contracts.py             # verify (exit 1 on any difference)
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CDIR = ROOT / "docs" / "research" / "contracts"
MANIFEST = CDIR / "FROZEN.sha256.json"


def current() -> dict[str, str]:
    files = sorted(p for p in CDIR.rglob("*") if p.is_file() and p.name != MANIFEST.name
                   and "__pycache__" not in p.parts and p.suffix in (".json", ".py", ".sql", ".md"))
    return {p.relative_to(CDIR).as_posix(): "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def diff() -> list[str]:
    pinned = json.loads(MANIFEST.read_text())["files"] if MANIFEST.exists() else {}
    now = current()
    out = [f"CHANGED {k}" for k in now if k in pinned and now[k] != pinned[k]]
    out += [f"ADDED   {k}" for k in now if k not in pinned]
    out += [f"REMOVED {k}" for k in pinned if k not in now]
    return out


if __name__ == "__main__":
    if "--write" in sys.argv:
        MANIFEST.write_text(json.dumps({"note": "Frozen contract bytes (ADR-0004/0010/0011). Changing a pinned file needs an accepted "
                                                "ADR and a semver bump; then regenerate with tools/pin_contracts.py --write.",
                                        "files": current()}, indent=2) + "\n")
        print(f"pinned {len(current())} files")
        raise SystemExit(0)
    d = diff()
    print("\n".join(d) or f"OK: {len(current())} contract files match the pin")
    raise SystemExit(1 if d else 0)
