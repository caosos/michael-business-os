# Card enrichment on lane D (D-16, ADR-0011)

Lanes attach enrichment blocks to Items without a contract change:
1. The block is stored as a content-addressed artifact (`mbos.put_artifact`).
2. An entry is added to `Item.research[]`: `{"field": "card.<block>", "source_uri": "artifact:sha256:<hex>", "finding", "basis", "provenance_id"}`.
3. The Operator UI reads it back through `mbos.v_item_card_inputs`.

## Answers to the D-16 questions (FACT, tested in `state/tests/test_d16_card_inputs.py`)
| Question | Answer |
|---|---|
| Can the UI/reader roles read enrichment artifact content? | **Yes.** `agent_read` (`mbos_reader`) and `approver` (`mbos_operator_ui`) can SELECT `mbos.artifacts.content` directly and the new view. Inline artifacts only: `fs`-stored blobs have no `content` and are read with `ArtifactStore` |
| Can lane agents patch `research` through `update_item_doc`? | **Yes**, for roles with EXECUTE (`agent_write`, which includes `mbos_dbos`, and `gateway`). `reader` and `approver` cannot (they get `InsufficientPrivilege`), and the UI cannot create artifacts either |
| Is it safe when two lanes enrich the same item at once? | **Not through `update_item_doc`.** It replaces `research[]`, so a read-modify-write loses entries. Reproduced: `card.comps` vanished and only `card.photos` survived. Use `mbos.append_item_research` instead |

## `mbos.append_item_research(item_id, entries jsonb[], actor, intent, provenance_ids, idempotency_key, receipt_type='ITEM_STATE_CHANGED', extra='{}')`
- Locks the item row, **then** reads `research[]`, then writes `research[] || entries`. No entry is lost: 12 concurrent enrichments all survive in the test.
- It is receipted like any other Item change, and it is replay-safe on the idempotency key (the second call returns the first receipt without a second append).
- It validates that the entries are a non-empty JSON array (MB004), and that the item exists (MB404).
- Granted to `agent_write` and `gateway` only.

**Request to Agent 01 (`spine_d.record_enrichment`):** replace the Python read-modify-write (`read_item` → `_patch` with `research + [entry]`) with a single `SELECT mbos.append_item_research(...)` call.

## `mbos.v_item_card_inputs`
One row per `(item, block)`, showing the **latest** entry for the block (earlier entries stay in `research[]` as history).

| Column | Meaning |
|---|---|
| `item_id`, `lane`, `category`, `state` | the Item |
| `block` | the part after `card.` |
| `research_index` | 1-based position in `research[]` (a later one supersedes an earlier one) |
| `finding`, `basis`, `provenance_id`, `source_uri` | from the research entry |
| `artifact_sha256`, `media_type`, `storage`, `location` | the artifact index row |
| `data` | the JSON content (inline artifacts only; NULL if the bytes are not valid JSON, or fs-stored) |
| `artifact_missing` | true if the entry cites no artifact, or one that is not indexed (the UI should show "evidence missing", not crash) |

A malformed artifact can never break a UI query: parsing goes through `mbos.try_jsonb`, which returns NULL instead of raising.
