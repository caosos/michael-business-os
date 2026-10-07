"""Fixed-vocabulary title tokens (shared by comps selection and transport classification).

Free text never becomes a number: a title is matched ONLY against the closed per-category vocabulary in
``estimation-priors.json`` ``comps_query`` (lower-case, word-bounded, 'N x M' normalized to 'NxM').
"""

from __future__ import annotations

import re

from .config import ScoringConfig

_SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\b")


def query_key(category: str, title: str | None, priors: ScoringConfig) -> dict[str, str]:
    """First vocabulary token per group found in ``title``."""
    vocab = priors.get("comps_query").get(category) or {}
    text = _SIZE.sub(lambda m: f"{m.group(1)}x{m.group(2)}", (title or "").lower())
    key: dict[str, str] = {}
    for group in sorted(k for k in vocab if not k.startswith("_") and k != "basis"):
        for token in vocab[group]:
            if re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text):
                key[group] = token
                break
    return key
