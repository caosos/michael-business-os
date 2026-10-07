# Receipt: E-06, PDP policy in lane D's Postgres (Agent 05)

- **Date:** 2026-10-07
- **Task:** E-06 (READY_QUEUE @ `8c3e4fd`)
- **External effects:** none.

## Built
- **`policy_pg.publish()` / `mbos-gov policy publish`.**
  - It validates the files with both the adjacent schema and the **packaged** schema.
  - It publishes only the keys that changed, in one `policy_admin` transaction, through `mbos.publish_policy`. Each key gets a `CONFIG_VERSION_BUMPED` receipt, and the provenance records the file hashes.
  - Keys published: `governance:policy/1`, `governance:content_rules/1`, `category:*` (11), `capability:*` (12).
- **`PgPolicyStore` (`current()`, `content_rules_store()`).** It reads `policy_current` and fails closed on any of these:
  - no row
  - a database error
  - a document that fails the schema pinned in code
  - a hash that does not match the recorded version
  - per-key rows that disagree with the document
- The gateway takes its content rules from the same source as its policy. `spine_adapter.build(dsns)` defaults to the database policy, and the CLI uses it when `MBOS_POLICY_SOURCE=db`.
- `schemas/policy.schema.json` is the packaged copy, byte-identical to `policy/policy.schema.json` (test-enforced).

## Verification (FACT)
- 14 E-06 tests pass, and the full suite (247 tests) passes on PG16 with lane D @ `14bd690`.
- **Parity:** the database policy gives identical decisions, tiers, reasons and policy_version to the file for all 11 categories plus the deny cases.
- **Publishing:** re-publishing is a no-op, and a change re-versions only the affected key.
- **Agents cannot publish** (InsufficientPrivilege). Lane D refuses a `category:money` row with `allow` (CheckViolation).
- **Fail closed:** a loosened file is refused at publish and nothing is written. A tampered document (loosened, or silently edited) is unavailable. A hand-edited matrix row that drifts from the document is unavailable.
- **Full gateway flow on the database policy:** propose → YES → executed (dry-run). The secret scan also reads its rules from the database.
