"""P-02-14: model-year forms real listings use (`'18`, `MY2018`, `MY18`) for Agent 03's KB matcher.

`mbos_economics.valueadd.listing_years` reads only four-digit years (two-digit numbers are not years there). This
module reads the extra shorthand forms and hands the matcher an item whose title also states the year in four digits,
so the matcher's own year logic decides hit / blocked. Every year read here is an INFERENCE (a seller's shorthand),
never a FACT; nothing is guessed from bare numbers, part numbers, measurements or prices.
"""

import copy
import re
from typing import Optional

MIN_YEAR, MAX_YEAR = 1950, 2035
# two-digit pivot: 'YY <= 35 -> 20YY, otherwise 19YY (matches the matcher's 1950-2035 window)
_PIVOT = 35

_NOT_BEFORE = r"(?<![A-Za-z0-9$#/.\-])"                    # "5'10", "PN'18", "$'18", "A-'18" are not model years
_NOT_AFTER = r"(?![A-Za-z0-9\"'″%]|[-/.]\d|,\d)"      # '18", 18% , MY18-4420, MY2018A, '18.5 are not model years
_APOS = r"['’‘]"
_RE_APOS = re.compile(_NOT_BEFORE + _APOS + r"(\d{2})" + _NOT_AFTER)
_RE_MY = re.compile(_NOT_BEFORE + r"MY[ \-]?(\d{4}|\d{2})" + _NOT_AFTER, re.IGNORECASE)
_RE_FOUR = re.compile(r"(?<![\d$#.,/\-])(19[5-9]\d|20[0-3]\d)(?![\d%]|[,.]\d|\s?(?:w|watts?|lbs?|gal|psi|btu|kw|hp|cc)\b)", re.IGNORECASE)


def _expand(two: str) -> int:
    n = int(two)
    return 2000 + n if n <= _PIVOT else 1900 + n


def extract_model_years(title: str) -> list[dict]:
    """`[{"year": 2018, "evidence": "MY2018", "basis": "INFERENCE"}]` for each shorthand year in the title."""
    out: list[dict] = []
    seen: set[int] = set()
    for rx in (_RE_APOS, _RE_MY):
        for m in rx.finditer(title or ""):
            g = m.group(1)
            y = int(g) if len(g) == 4 else _expand(g)
            if not MIN_YEAR <= y <= MAX_YEAR or y in seen:
                continue
            seen.add(y)
            out.append({"year": y, "evidence": m.group(0).strip(), "basis": "INFERENCE"})
    return sorted(out, key=lambda r: r["year"])


def for_kb_match(item: dict) -> tuple[dict, list[dict]]:
    """A copy of the Item whose normalized title also states each shorthand year in four digits, plus the extractions.

    The input Item is never modified. A year the title already states in four digits is not added again.
    """
    title = ((item.get("normalized") or {}).get("title")) or ""
    found = extract_model_years(title)
    stated = {int(m.group(1)) for m in _RE_FOUR.finditer(title)}
    extra = [r for r in found if r["year"] not in stated]
    if not extra:
        return item, found
    aug = copy.deepcopy(item)
    aug["normalized"]["title"] = title + " " + " ".join(str(r["year"]) for r in extra)
    return aug, found


def card_line(found: list[dict]) -> Optional[str]:
    """What the card may say: an INFERENCE, never a statement of fact about the unit."""
    if not found:
        return None
    parts = ", ".join(f"{r['year']} (read from \"{r['evidence']}\")" for r in found)
    return f"INFERENCE: model year {parts} is the seller's shorthand in the title; not confirmed"
