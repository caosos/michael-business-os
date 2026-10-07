# ADR-0009: Contracts v1.1.0 (PROPOSED, NOT applied)

- **Status:** PROPOSED (Agent 01, 2026-10-07). Frozen contracts **v1.0.0 stay in force** until this is ACCEPTED.
- **Context:** round-two implementation surfaced gaps in all six lanes. The full list, with who asked and why, is in `docs/integration/ROUND_TWO_INTEGRATION.md` §4.
- **Rule:** no lane edits frozen v1.0.0 files. Every lane already keeps byte-identical copies (FACT, sha256 check on 2026-10-07).

## Proposed changes (all additive, except item 1 which corrects an example)
1. **MOVED to ADR-0010 (ACCEPTED).** Remaining here: regenerate the example hash at v1.1.0. Originally: make canonical JSON normative for every hash: `sort_keys`, `separators=(",",":")`, `ensure_ascii=False`, UTF-8, sha256, written `sha256:<hex>`. Regenerate `action-request-email-held.example.json`'s `payload_hash`, which does not reproduce today (FACT).
2. Add Receipt types `ITEM_UPDATED`, `ACTION_EXPIRED`, `GUARD_REFUSED`, `ACTION_STATUS_CHANGED` and `SOURCE_FROZEN`. Allow expiry receipts without `approval_id`.
3. Add ActionRequest status `superseded`, used by MODIFY.
4. Register ID prefixes `lsn_`, `pol_`, `bud_`, `obx_` and `pdp_`.
5. Make `Item.sources[].raw_ref` required.
6. Re-vendor Agent 03's schemas as v1.1.0 under **versioned `$id`s**. Adopt 03's `inputs_hash` spec `mbos.economics.inputs/v1`. Annotate the illustrative trailer example, which 03's engine scores PASS (C23).
7. Item-level semantics when one Item has more than one ActionRequest.
8. `validate_contracts.py` adds a format checker.

## Acceptance gate
- Every lane re-runs its contract tests against v1.1.0.
- A10 conformance passes on the converged store.
- Agent 01 bumps `schema_version` and updates `ContractModel` alignment tests.
- Owner impact: none. This is technical, not a MICHAEL_DECISIONS item.
