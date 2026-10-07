# Receipt: C-03, versioned `$id`s for the v1.1.0 schemas (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-03` (READY_QUEUE @ agent-01 `99e9ec0` / `bf215b2`). Claimed at `73a4d32`. Code at `22b49e6`.
- **Scope:** this branch only. No frozen v1.0.0 file was edited anywhere.

## Change
| Schema | v1.0.0 `$id` (vendored by Agent 01) | v1.1.0 `$id` (this branch) |
|---|---|---|
| opportunity | `https://michael-business-os/schemas/opportunity.schema.json` | `https://michael-business-os/schemas/agent-03/v1.1.0/opportunity.schema.json` |
| service-job | `…/schemas/service-job.schema.json` | `…/schemas/agent-03/v1.1.0/service-job.schema.json` |
| scorecard | `…/schemas/scorecard.schema.json` | `…/schemas/agent-03/v1.1.0/scorecard.schema.json` |

- **Why a version path segment:** the relative `"$ref": "scorecard.schema.json"` inside opportunity and service-job then resolves within the same version, with no edit.
- `economics/tests/contracts/vendor/agent-03/` pins Agent 01's v1.0.0 copies (@ `99e9ec0`). FACT: they are byte-identical to round-one `b032676` (`cmp`).

## Acceptance evidence (FACT)
- The new `$id`s are asserted by `tests/test_contracts.py::test_schema_ids_versioned`. v1.0.0 and v1.1.0 load into one registry without collision.
- Every golden and every estimated Agent 02 Item still validates against **frozen Item v1.0.0**. In addition, each economics block and scorecard validates against the **v1.1.0** schemas by their new `$id`s.
- Suite: **104 passed, 70 subtests** (py3.12 + jsonschema); **104 OK, 5 skipped** (py3.10 stdlib, no jsonschema).

## For Agent 01 (ADR-0009 item 6)
Re-vendor `docs/research/schemas/*.schema.json` @ `22b49e6` into `contracts/vendor/agent-03/` under these `$id`s, then re-pin `item.schema.json`'s `$ref`s. 03's v1.1.0 is additive, so the 13 goldens already validate under both versions.
