# Canonical serialisation and receipt hashing (ADR-0010): NORMATIVE

This folder is part of the frozen contract set. Every lane MUST hash with it. It answers QA findings F-13 and F-14.

| File | What it is |
|---|---|
| `mbos_canonical.py` | Reference implementation, stdlib only. Vendor it byte-identical, or match `vectors.json` exactly |
| `mbos_canonical.sql` | PostgreSQL twin. The ledger owner (Agent 04) installs it |
| `vectors.json` | Golden vectors: 10 canonical forms, 6 rejections and a 2-receipt chain. Self-test: `python -I mbos_canonical.py vectors.json` |

## MBOS-CJSON-1: what every hash is computed over

MBOS-CJSON-1 is RFC 8785 (JCS) with an I-JSON profile. It is used for `payload_hash`, `inputs_hash`, content hashes, the hash Michael sees, and `row_hash`.

**Numbers**
- Every number is the IEEE-754 double nearest to the JSON value.
- It is written the way ECMAScript `Number.prototype.toString` writes it:
  - `850.0` → `850`
  - `3.20` → `3.2`
  - `-0.0` → `0`
  - `1e-7` → `1e-7`
  - `0.000001` → `0.000001`
- Floats are **allowed**. Money stays a JSON number of dollars.
- A number whose value is integral must satisfy |n| ≤ 2^53−1, whatever its literal form (`1e21` is rejected too).
- NaN and ±Infinity are rejected.

**Objects:** members are sorted by name in code-point order. Names must be BMP-only, which makes code-point order identical to UTF-16 order and to PostgreSQL `COLLATE "C"`. Duplicate names are rejected.

**Strings:** escaped as `JSON.stringify` does: `\" \\ \b \f \n \r \t`, with other C0 characters as lowercase `\u00xx`. Everything else is literal UTF-8. U+0000 and lone surrogates are rejected.

**Layout:** no insignificant whitespace. The hash is `sha256:` followed by the lowercase hex SHA-256 of the UTF-8 bytes.

## MBOS-RH-1: receipt `row_hash`

```
row_hash = "sha256:" + hex(SHA-256(UTF-8(MBOS-CJSON-1(D))))
D = the Receipt v1 document, minus row_hash, INCLUDING seq and prev_hash.
    Every TOP-LEVEL member whose value is null is dropped, except prev_hash,
    which is always present (null only at genesis). Nested nulls are kept.
```

- There is no separate `|| prev_hash` concatenation; `prev_hash` is inside `D`. This supersedes the non-normative prose in `receipt.schema.json` `row_hash.description`. The schema file itself is unchanged, so every lane's pins stay valid.
- Receipt `ts` MUST be `YYYY-MM-DDTHH:MM:SS.ffffffZ`: UTC, with exactly 6 fractional digits. The ledger normalises it before hashing.
- **Ledger owner:** Agent 04 (`mbos.receipts`, written only through its `append_receipt`). Every other lane's receipt table is a test stand-in. It may exist for tests, but it must use MBOS-RH-1.
