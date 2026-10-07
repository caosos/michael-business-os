"""MBOS-CJSON-1 and MBOS-RH-1 reference implementation (ADR-0010). Normative; stdlib only; vendor as-is.

MBOS-CJSON-1 = RFC 8785 JSON Canonicalization Scheme (JCS) with an I-JSON profile:
  * numbers: IEEE-754 doubles serialised as ECMAScript Number.prototype.toString (850.0 -> "850", 3.20 -> "3.2")
  * any number with an integral value must satisfy |n| <= 2**53 - 1 (written 1e21 or 1000… alike);
    NaN / Infinity are rejected
  * object member names must be BMP-only strings (then UTF-16 code-unit order == code point order ==
    PostgreSQL COLLATE "C" byte order), and no string may contain U+0000 or a lone surrogate
  * no whitespace; strings escaped exactly as JSON.stringify (\\b \\t \\n \\f \\r \\" \\\\, other C0 as \\u00xx)

MBOS-RH-1 (receipt row_hash):
  row_hash = "sha256:" + hex(SHA-256(UTF-8(CJSON(D))))
  D = the Receipt v1 document without `row_hash`, including `seq` and `prev_hash`, with every TOP-LEVEL
      member whose value is null removed EXCEPT `prev_hash`, which is always present (null only at genesis).

Self-test:  python -I mbos_canonical.py vectors.json
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

SPEC = "MBOS-CJSON-1"
MAX_SAFE_INT = 2**53 - 1


class CanonicalError(ValueError):
    pass


def _number(x: Any) -> str:
    if isinstance(x, int):
        if abs(x) > MAX_SAFE_INT:
            raise CanonicalError(f"integer {x} outside +/-(2**53-1) (I-JSON)")
        x = float(x)
    if not math.isfinite(x):
        raise CanonicalError("NaN/Infinity are not JSON")
    if x.is_integer() and abs(x) > MAX_SAFE_INT:  # literal form (1e21 vs 1000…) is lost in many parsers, incl. jsonb
        raise CanonicalError(f"integral value {x!r} outside +/-(2**53-1) (I-JSON)")
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    t = Decimal(repr(abs(x))).as_tuple()  # repr == shortest round-trip digits
    digits = "".join(map(str, t.digits)).rstrip("0") or "0"
    n = len("".join(map(str, t.digits))) + t.exponent  # value = 0.<digits> * 10**n
    k = len(digits)
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        s = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e > 0 else "-") + str(abs(e))
    return sign + s


def _string(s: str) -> str:
    if "\x00" in s or any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        raise CanonicalError("strings must not contain U+0000 or lone surrogates")
    return json.dumps(s, ensure_ascii=False)


def _key(k: Any) -> str:
    if not isinstance(k, str):
        raise CanonicalError(f"object member name must be a string, got {type(k).__name__}")
    if any(ord(c) > 0xFFFF for c in k):
        raise CanonicalError(f"object member name {k!r} contains a non-BMP character")
    return k


def _enc(o: Any) -> str:
    if o is None:
        return "null"
    if o is True:
        return "true"
    if o is False:
        return "false"
    if isinstance(o, (int, float)):
        return _number(o)
    if isinstance(o, Decimal):
        return _number(float(o))
    if isinstance(o, str):
        return _string(o)
    if isinstance(o, dict):
        keys = sorted(_key(k) for k in o)
        if len(keys) != len(o):
            raise CanonicalError("duplicate member names")
        return "{" + ",".join(_string(k) + ":" + _enc(o[k]) for k in keys) + "}"
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(_enc(v) for v in o) + "]"
    raise CanonicalError(f"cannot canonicalise {type(o).__name__}")


def canonical_json(obj: Any) -> str:
    """MBOS-CJSON-1 text."""
    return _enc(obj)


def canonical_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_of(obj: Any) -> str:
    """`sha256:<hex>` of MBOS-CJSON-1: payload_hash, inputs_hash, content hashes."""
    return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def receipt_hash_document(receipt: dict) -> dict:
    """D for MBOS-RH-1."""
    d = {k: v for k, v in receipt.items() if k != "row_hash" and (v is not None or k == "prev_hash")}
    d.setdefault("prev_hash", None)
    return d


def receipt_row_hash(receipt: dict) -> str:
    return sha256_of(receipt_hash_document(receipt))


def verify_chain(receipts: list[dict]) -> tuple[bool, str]:
    """Verify an exported chain (ordered by seq) using only this module."""
    prev = None
    for i, r in enumerate(receipts):
        if i and r["seq"] != receipts[i - 1]["seq"] + 1:
            return False, f"gap before seq {r['seq']}"
        if r.get("prev_hash") != prev:
            return False, f"seq {r['seq']}: prev_hash does not link"
        if receipt_row_hash(r) != r["row_hash"]:
            return False, f"seq {r['seq']}: row_hash mismatch"
        prev = r["row_hash"]
    return True, f"{len(receipts)} receipts verified"


def _self_test(path: str) -> int:
    v = json.loads(open(path, encoding="utf-8").read())
    bad = 0
    for case in v["cjson"]:
        got = canonical_json(json.loads(case["input"]))
        ok = got == case["canonical"] and sha256_of(json.loads(case["input"])) == case["sha256"]
        bad += not ok
        print(("PASS " if ok else "FAIL ") + case["name"] + ("" if ok else f"\n   got {got}"))
    for case in v["reject"]:
        try:
            canonical_json(json.loads(case["input"]))
            print("FAIL reject " + case["name"]); bad += 1
        except CanonicalError:
            print("PASS reject " + case["name"])
    ok, msg = verify_chain(v["receipt_chain"])
    bad += not ok
    print(("PASS " if ok else "FAIL ") + "receipt_chain: " + msg)
    return 1 if bad else 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_self_test(sys.argv[1]))


# =====================================================================================================
# Agent 03 lane additions. Everything ABOVE this banner is the ADR-0010 reference `mbos_canonical.py`
# (agent-01 @ 99e9ec0), byte-identical; tests/test_adr0010.py enforces it. Re-vendor by replacing that
# prefix only. Everything below is lane-C helpers built ON the reference (no second canonical form).
# =====================================================================================================

from datetime import datetime, timezone  # noqa: E402

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(obj: Any) -> str:
    """``sha256:<hex>`` of MBOS-CJSON-1 (the reference ``sha256_of``). Decimals hash as their nearest double."""
    return sha256_of(obj)


def parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone: {ts!r}")
    return dt.astimezone(timezone.utc)


def derived_ulid(prefix: str, ts: str, seed: str) -> str:
    """Deterministic ULID-shaped id: 48-bit time part from ``ts``, 80-bit tail from sha256(seed).

    IDs are derived, not random: replaying the same inputs at the same ``ts`` reproduces them.
    The engine never reads the wall clock.
    """
    ms = int(parse_ts(ts).timestamp() * 1000)
    if not 0 <= ms < 2**48:
        raise ValueError("timestamp out of ULID range")
    tail = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:10], "big")
    n = (ms << 80) | tail
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[n & 31])
        n >>= 5
    return f"{prefix}_" + "".join(reversed(chars))
