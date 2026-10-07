# ADR-0010: One canonical JSON (MBOS-CJSON-1) and one receipt hash (MBOS-RH-1)

- **Status:** ACCEPTED. This is a coordinator technical ruling (2026-10-07), not a Michael decision.
- **Resolves:** QA findings F-13 (receipt hash mismatch) and F-14 (number canonicalisation), and ADR-0009 item 1.
- **Supersedes:** integration ruling R3's reference to `json.dumps` defaults for numbers. The `row_hash.description` prose in `receipt.schema.json` is non-normative and is superseded too.

## Context (FACT)
- One identical receipt produced three different `row_hash` values: 01 `seq|jsonb::text|prev`, 04 `sha256(jsonb::text(doc))`, and 05/06/07 `canonical(row)||prev_hash` (07 interop, on PostgreSQL 16).
- `{"offer": 850.0}` hashed differently between lanes:
  - 03 normalised through Decimal.
  - 01, 02, 06 and 07 emitted `850.0`.
  - 05 refused floats.
- `tools/interop_check.py` reproduces the number disagreement on every lane's pushed code. That is the baseline below.
- PostgreSQL `jsonb::text` is not a portable canonical form: it inserts `": "` and `", "` spacing and orders keys by length.

## Decision
1. **MBOS-CJSON-1** = RFC 8785 JCS with an I-JSON profile. The full rules are in `docs/research/contracts/canonical/README.md`.
   - It is chosen because it is a published standard that any language can implement.
   - It makes `850.0` and `850` hash the same.
   - Floats are permitted, which removes 05's refusal.
   - The profile limits make Python and PostgreSQL produce identical bytes: integral values within ±(2^53−1), and BMP-only member names. FACT: all 10 vectors, 6 rejections and the receipt vectors match in both `mbos_canonical.py` and `mbos_canonical.sql` on PostgreSQL 16.2.
2. **MBOS-RH-1** row_hash = sha256 over MBOS-CJSON-1 of the full receipt document D, with `seq` and `prev_hash` inside D. Top-level nulls are dropped except `prev_hash`, and `ts` is fixed to microsecond precision.
   - This is Agent 04's document shape, chosen so the ledger owner has the smallest change.
   - The canonical form is made portable, so any lane can verify an exported chain with ~150 lines of stdlib Python (`verify_chain`).
3. **One ledger owner: Agent 04.** Production receipts are written only through 04's `append_receipt`. Agent 01's `0001_spine.sql` receipts, and 05's and 06's SQLite receipts, are stand-ins that must still conform until removed.
4. **Contract mechanics.**
   - The new normative files sit in `docs/research/contracts/canonical/`. They are additive; no v1.0.0 schema file changes, so lane pins stay valid.
   - The frozen `action-request-email-held.example.json` hash stays as an illustrative v1.0.0 artefact. Its corrected value comes with the v1.1.0 regeneration (ADR-0009).

## Conformance (each lane; tasks are in `docs/status/READY_QUEUE.md`)
| Lane | Change | Acceptance |
|---|---|---|
| 01 | DONE: `mbos.hashing` loads the reference; migration `0003_canonical_rh1.sql`; fixed `ts`; pure-Python export verifier | 142 tests pass, including vectors in PG and Python and verification of a PG-written chain in Python |
| 02 | `ids.canonical_json` → reference | `tools/interop_check.py` row 02 = 10/10 |
| 03 | `canonical.py` → reference. Decimals are hashed as doubles; re-baseline the golden hashes in a config/engine note | interop 10/10; goldens replay |
| 04 | Install `mbos_canonical.sql`. `canonical := mbos.cjson(receipt_canonical(NEW))`, `row_hash := mbos.cjson_sha256(...)`, with `verify_chain` to match. Payload hashes use `mbos.cjson_sha256`, never `jsonb::text` | vectors pass in PG; an exported chain verifies with `mbos_canonical.verify_chain` |
| 05 | `payload_hash` uses the reference and drops the float refusal. The stand-in store's `row_hash` becomes MBOS-RH-1 | interop 10/10; vectors `receipt_chain` verify |
| 06 | `util.canonical_json` → reference. The stand-in store's `row_hash` becomes MBOS-RH-1 | interop 10/10 |
| 07 | `core.canonical` and `receipt_row_hash` → reference. Add `vectors.json` to `mbos_qa interop`, then re-run it | interop all lanes CONFORMS, with the result published |

## Consequences
- **Breaking for dev databases only.** Agent 01's `0003` refuses to run over pre-ADR-0010 receipts, so recreate dev DBs. No production chain exists, because nothing has been deployed.
- Agent 03's Decimal-precision hashes change wherever a value had more than 17 significant digits. That is acceptable, because the hashes are replay-checked within 03's own versioned golden set.
