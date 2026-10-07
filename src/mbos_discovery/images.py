"""Listing images as evidence for dedup — READY_QUEUE B-11 (image perceptual hashing).

* Images are fetched read-only through an injectable `ImageFetcher` (fixtures here; a live fetcher would sit behind
  the same allow-listed ReadOnlyTransport) and retained content-addressed like any raw payload. Their sha256 refs
  fill `Item.normalized.images` (the contract field).
* `phash(bytes)` is the classic 64-bit DCT perceptual hash: grayscale → 32×32 → 2-D DCT-II → top-left 8×8 minus
  DC → bits above the median. Robust to re-compression, resizing and mild crops; different photos of different
  units differ by many bits. Deterministic for a given decoder (Pillow).
* `compare(a, b)` over two Items' hash sets: MATCH if some pair is within MATCH_BITS, DIFFERENT if every pair is at
  least DIFFERENT_BITS apart, else INCONCLUSIVE. Dedup treats INCONCLUSIVE and "no images" as *no image evidence*
  (falls back to the listing-data rules) — images can only add certainty, never invent it.

Limits (stated): a dealer re-using the same stock photo for two physical units defeats image evidence (they look
identical); synthetic fixture photos are not real seller photos. Pillow is optional (`pip install .[images]`);
without it no image evidence is produced and behaviour is unchanged.
"""

from __future__ import annotations

import io
import math
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Optional, Protocol

MATCH_BITS = 10
DIFFERENT_BITS = 20
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MATCH, DIFFERENT, INCONCLUSIVE, NONE = "MATCH", "DIFFERENT", "INCONCLUSIVE", "NO_IMAGES"


class ImageFetcher(Protocol):
    def fetch(self, url: str) -> Optional[bytes]: ...


class FixtureImageFetcher:
    """Serves image URLs from local files: {url: path}. Unknown URL → None. Never touches the network."""

    def __init__(self, mapping: dict[str, str | Path]) -> None:
        self.mapping = {u: Path(p) for u, p in mapping.items()}
        self.calls: list[str] = []

    def fetch(self, url: str) -> Optional[bytes]:
        self.calls.append(url)
        p = self.mapping.get(url)
        return p.read_bytes()[:MAX_IMAGE_BYTES] if p and p.exists() else None


@lru_cache(maxsize=32)
def _dct_matrix(n: int) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple((math.sqrt(1 / n) if k == 0 else math.sqrt(2 / n)) * math.cos(math.pi * (2 * i + 1) * k / (2 * n))
                       for i in range(n)) for k in range(n))


def phash(data: bytes) -> str:
    """64-bit DCT pHash as 16 hex chars. Raises ValueError if the bytes are not a decodable image."""
    try:
        from PIL import Image
    except ImportError as e:  # pragma: no cover - optional dependency
        raise RuntimeError("Pillow not installed (pip install .[images])") from e
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"not a decodable image: {e}") from None
    px = list(img.convert("L").resize((32, 32), Image.Resampling.BILINEAR).tobytes())   # 8-bit gray, 1 byte/px
    m = [px[r * 32:(r + 1) * 32] for r in range(32)]
    c = _dct_matrix(32)
    rows = [[sum(c[k][i] * m[r][i] for i in range(32)) for k in range(8)] for r in range(32)]       # DCT along x
    coef = [[sum(c[k][r] * rows[r][j] for r in range(32)) for j in range(8)] for k in range(8)]     # then along y
    flat = [coef[k][j] for k in range(8) for j in range(8)][1:]                                   # drop DC
    med = sorted(flat)[len(flat) // 2]
    bits = 0
    for v in [coef[0][0]] + flat:
        bits = (bits << 1) | (1 if v > med else 0)
    return f"{bits & ((1 << 64) - 1):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def compare(a: Iterable[str], b: Iterable[str]) -> str:
    a, b = list(a), list(b)
    if not a or not b:
        return NONE
    best = min(hamming(x, y) for x in a for y in b)
    if best <= MATCH_BITS:
        return MATCH
    if best >= DIFFERENT_BITS:
        return DIFFERENT
    return INCONCLUSIVE


def collect(urls: list[str], fetcher: Optional[ImageFetcher], put: Callable[[bytes], str],
            limit: int = 4) -> tuple[list[str], list[str]]:
    """Fetch up to `limit` images, retain them (`put` → sha256 ref), hash them. Returns (refs, phashes); undecodable
    or missing images are skipped (never fatal)."""
    refs, hashes = [], []
    if fetcher is None:
        return refs, hashes
    for url in urls[:limit]:
        try:
            data = fetcher.fetch(url)
            if not data:
                continue
            h = phash(data)
        except Exception:  # noqa: BLE001 — an image problem never breaks discovery
            continue
        ref = put(data)
        if ref not in refs:
            refs.append(ref)
            hashes.append(h)
    return refs, hashes
