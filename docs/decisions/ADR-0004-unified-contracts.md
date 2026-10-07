# Decision

ADR-0004 — Unified contracts: Item v1, ActionRequest, Approval, Receipt, Provenance, Outcome

Status: ACCEPTED (2026-10-06, Agent 01): contracts are frozen at v1.0.0. Changes need Agent 01 sign-off and a semver bump.

## Context
Six specialists produced six incompatible data models:
- 02: a flat SQLite record.
- 03: flip, service and scorecard JSON Schemas.
- 04: 23 relational entities plus a `receipts` DDL.
- 05: ActionRequest, Approval and lifecycle-event receipts.
- 06: a comms receipt.
- 07: approval and attribution objects.

They disagree on IDs, field names, verdict vocabularies and the shape of a receipt. Without one contract the agents cannot interoperate.

## Decision
Machine-readable contracts (JSON Schema 2020-12) are in `docs/research/contracts/`, validated by `validate_contracts.py` together with worked examples:

| Contract | Owner (content) | Built from |
|---|---|---|
| `item.schema.json` | 01 | 01's envelope + 02's `normalized` + 03's `economics`/`scores`, referenced verbatim from `vendor/agent-03/` |
| `action-request.schema.json` | 05 | 05 §4.1/§4.3 + Item linkage |
| `approval.schema.json` | 05 / 06 UX | 05 §4.2 + 01's HOLD wake semantics |
| `receipt.schema.json` | storage 04, events 05 | merge of 01 + 04 §4 + 05 §11 + 06 §13 (`details.kind=comms`) + 07 |
| `provenance.schema.json` | 04 | 04 §5 + 01's resolution rule (anyOf: source / model / human / tool) |
| `outcome.schema.json` | 04 store, 03 consumer | 03 §16 LEARN signals + 07 §13 attribution |

Key rulings:
1. **One envelope, two lanes** (ADR-0007). `type ∈ {flip, service}`. The `category` enum is limited per type. `economics` must be 03's flip block or service block according to `type`. Schema conditionals enforce both.
2. **IDs.** Every exposed ID is a prefixed ULID (`itm_ areq_ appr_ rcpt_ prov_ outc_ scr_ rec_`). The ledger orders the hash chain with an internal `seq bigint`. This reconciles 04 (bigint/uuid) with 05 (prefixed ULID).
3. **Two vocabularies, never conflated.**
   - `recommendation.verdict` is YES/MAYBE/PASS, the machine verdict from Agent 03.
   - `approval.decision` is YES/NO/MODIFY/HOLD, Michael's decision.
   - Routing: PASS archives with a receipt and sends no ping. MAYBE loops back to RESEARCH on `cheapest_decisive_evidence`, or goes into the daily digest. YES creates ActionRequest(s) that need approval.
   - 06's approve/edit/reject maps to YES/MODIFY/NO, with HOLD added.
4. **Two state machines, nested.**
   - The Item `state` tracks the business flow (DISCOVERED … LEARNED/ARCHIVED).
   - Each side effect is an ActionRequest with 05's status machine.
   - MODIFY never mutates anything. It creates a new ActionRequest with `derived_from`.
5. **Receipts are lifecycle events** (05's model). They are stored insert-only with a hash chain (04's model) and committed in the same transaction as the state change (01's model). A receipt needs at least one `provenance_id`. Effector receipts carry `effector_response.dry_run=true` throughout Round One and the MVP.
6. **The Item references records; it never embeds them.** ActionRequests, approvals, receipts, outcomes and provenance are separate append-only rows. The Item stores their IDs.
7. **Evidence tags.** The canonical set is FACT / INFERENCE / RECOMMENDATION / UNKNOWN. 03's `estimates_meta.assumptions[].basis` (FACT/INFER/REC/UNK) is accepted as a short alias inside vendor blocks only.
8. **Canonical field mappings.**

   | Agent 02 field | Canonical field |
   |---|---|
   | `distance_miles` | `normalized.location.road_miles_one_way` |
   | `source` (scalar) | `sources[]` (array) |
   | `opportunity_type` | `opportunity_kind` |
   | `valuation{}` / `score` | removed; values come from 03's scorecard |
   | `comps{}` | 03 `estimates_meta.comps[]` |

## Evidence
- FACT: the schemas are valid 2020-12 and every example in `contracts/examples/` validates. Negative tests confirm the schemas reject:
  - a receipt without provenance
  - an irreversible action at tier > 0
  - a flip carrying a service category
  - a service item carrying flip economics
- Sources: 02 ADR-0201 and §6–7; 03 `schemas/*.json`; 04 §3–5; 05 §4, §11; 06 §13; 07 §13, §15.

## Risks
- 03's economics schemas are referenced verbatim, so a breaking change by 03 breaks Item v1. Mitigation: 03 bumps `$id`/version and 01 re-pins.
- JSON Schema cannot express DB-level invariants (insert-only, same-transaction). 04's DDL must enforce those, and the acceptance suite tests them (integration doc §8).

## Reversibility
High. The schemas are documents. The expensive part to change later is the receipt ledger shape, which is why it is frozen now.

Coordinator review required: NO (this is the coordinator's decision). Specialist objections go to `docs/status/ALL_AGENTS.md` → Cross-Agent Conflicts.
