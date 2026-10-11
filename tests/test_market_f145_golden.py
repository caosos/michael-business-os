"""F-145: GSA page output is unchanged by the source seam (golden comparison, csrf/nonce masked). Regenerate with MBOS_WRITE_GOLDEN=1 only for an intended GSA change."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests.test_market_f47 import cache, get, req, ui  # noqa: F401

GOLDEN = Path(__file__).parent / "fixtures" / "f145_gsa_golden.json"
CASES = {"gallery": dict(go=1, keywords="trailer"), "list": dict(go=1, keywords="trailer", view="list"), "gsa_explicit": dict(go=1, source="gsa", broad=1, radius="150"),
         "default": {}, "state": dict(go=1, loc_mode="state", state="AR", broad=1)}


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def mask(h: str) -> str:
    h = re.sub(r"(name='(?:csrf|nonce)' value=')[^']*", r"\1X", h)
    h = re.sub(r"\(\d+(?:\.\d+)? h (ago|old)\)", r"(N h \1)", re.sub(r"STALE \((\d+(?:\.\d+)?) h old\)", "STALE (N h old)", h))      # wall-clock age of the cache
    return re.sub(r"<select form='mkform' name='source'>.*?</select>", "<SOURCE-SELECT/>", h)    # F-145 intentionally adds source choices; the rest of the page must not change


def test_gsa_pages_match_golden(ui):
    got = {k: mask(get(ui, **v)) for k, v in CASES.items()}
    if os.environ.get("MBOS_WRITE_GOLDEN"):
        GOLDEN.write_text(json.dumps(got, indent=0, sort_keys=True))
    want = json.loads(GOLDEN.read_text())
    assert got.keys() == want.keys()
    for k in got:
        if got[k] != want[k]:
            import difflib
            d = [x for x in difflib.unified_diff(want[k].split("><"), got[k].split("><"), lineterm="", n=0) if x[:1] in "+-" and x[:3] not in ("+++", "---")]
            raise AssertionError(k + ": " + " | ".join(d)[:1500])
