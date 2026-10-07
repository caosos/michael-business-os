# Receipt — Round-One Reconciliation (Agent 01)

- **Timestamp:** 2026-10-06. Peer status timestamps are partly UTC (2026-10-07T04:0xZ).
- **Agent:** 01 (Coordinator / Architect).
- **Action:** read all six specialist round-one deliverables, ruled on the conflicts between them, and published the integrated architecture, frozen contracts and ADRs. Docs only: nothing was deployed, contacted, purchased or published. No other branch was modified.
- **Related outputs:**
  - `docs/research/agent-01-integration.md`
  - `docs/research/contracts/`
  - `docs/decisions/ADR-0001..0008`
  - `docs/decisions/INDEX.md`
  - `docs/status/ALL_AGENTS.md`
- **Confidence:**
  - High: the conflict identification and the contract merge. Both are traceable to cited peer sections.
  - Medium: the rubric scores. They are judgment calls, with per-dimension inputs listed below.

## Provenance — inputs read
All files were read with `git show origin/<branch>:<path>`. Nothing was checked out.

| Agent | Branch | Commit | Files |
|---|---|---|---|
| 02 | research/agent-02-opportunity | da52612 | research, ADR-0201, ADR-0202, receipt, status |
| 03 | research/agent-03-economics | b032676 | research, ADR-001, receipt, `config/scoring-config.json`, `schemas/{opportunity,service-job,scorecard}.schema.json`, status |
| 04 | research/agent-04-state | be6aed9 | research, ADR-0001, receipt, status |
| 05 | research/agent-05-governance | 5ee191d | research, ADR-001, ADR-002, receipt, status |
| 06 | research/agent-06-communications | c7af3bb | research, ADR-001, ADR-002, receipts 01–04, status |
| 07 | research/agent-07-marketing | 68dd3e8 | research, ADR-0001, ADR-0002, receipt, status |

- **Vendored:** Agent 03's three schemas were copied byte-for-byte from b032676 to `docs/research/contracts/vendor/agent-03/`. Agent 03 keeps ownership of them.
- **Human input:** Michael's scope clarification (2026-10-06), recorded verbatim in ADR-0007: value-add flips and paid services, not narrowed to cars or home services.

## Method
1. Three parallel read-only summarization passes, covering agents 02+03, 04+05 and 06+07.
2. Each summary extracted: stack, conflicts with 01, schemas, ADRs, MVP, UNKNOWNs, needs, and coverage against the "exact info required" list.
3. Every conflict was scored with the §7 rubric. Weights: provenance ×3, safety ×3, durability ×2.5, ops ×2, license ×2, maintenance ×1.5, capability ×1.5, interop ×1.5, reversibility ×1. Maximum score 90.

### Rubric inputs (0–5 per dimension, in weight order: prov, safe, dur, ops, lic, maint, cap, interop, rev)
| Option | prov | safe | dur | ops | lic | maint | cap | interop | rev | Total |
|---|---|---|---|---|---|---|---|---|---|---|
| Postgres | 5 | 4 | 5 | 4 | 5 | 5 | 5 | 5 | 4 | **84.0** |
| SQLite | 2 | 3 | 3 | 5 | 5 | 5 | 2 | 2 | 4 | 60.0 |
| DBOS | 5 | 4 | 5 | 5 | 5 | 4 | 3 | 5 | 4 | **81.5** |
| Temporal | 4 | 4 | 5 | 2 | 5 | 5 | 5 | 4 | 3 | 74.5 |
| n8n as backbone | 2 | 2 | 3 | 4 | 2 | 5 | 4 | 2 | 3 | 51.0 (fails the gate as system of record) |
| Postgres SoR + Twenty projection | 5 | 4 | 5 | 3 | 4 | 4 | 4 | 5 | 5 | **78.0** |
| Twenty as SoR | 2 | 3 | 4 | 4 | 3 | 5 | 5 | 2 | 2 | 59.0 |
| Merged PANIC | 5 | 5 | 4 | 3 | 5 | 4 | 5 | 5 | 4 | **81.0** |
| Agent 05 freeze only | 5 | 3 | 4 | 4 | 5 | 4 | 3 | 4 | 4 | 72.5 |
| Telegram bot | 4 | 4 | 4 | 5 | 4 | 5 | 4 | 5 | 5 | **78.0** |
| Web approval UI | 5 | 5 | 4 | 2 | 5 | 3 | 5 | 5 | 4 | 77.5 |
| ntfy/Apprise | 2 | 2 | 3 | 5 | 5 | 4 | 2 | 3 | 5 | 58.0 |

## Verification performed
- `validate_contracts.py`, run with jsonschema in a scratch venv. Results:
  - 9 schemas pass `check_schema` (6 contracts + 3 vendored).
  - 7/7 examples PASS.
  - 4 negative invariant tests are correctly rejected: receipt without provenance; irreversible action at tier 1; flip with a service category; service with flip economics.
- **Coverage check against what peers asked of the coordinator:** every item has an answer.

| Peer request | Answered in |
|---|---|
| 02: reconcile ADR-0201 with 03/04/06 | ADR-0004 |
| 02: reconcile ADR-0202 with 05 | INDEX / ADR-0005 |
| 02: ntfy overlap | ADR-0006 |
| 02: ADR numbering | INDEX |
| 03: schema from 02 | Item v1 |
| 03: ids / outcome store / receipt from 04 | ADR-0004 |
| 03: approval interface / caps from 05 | ADR-0004/0005 |
| 04: reconcile with 03/05/06 | ADR-0004 |
| 05: reconcile ADR-001/002 | ADR-0005, INDEX |
| 05: shared receipt with 04 | ADR-0004 |
| 05: `score_ref` | `scorecard_id` |
| 05: gate placement in the flow | integration §2/§4 |
| 05: comms points with 06 | ADR-0005/0006 |
| 06: ADR review | INDEX |
| 06: receipt schema | ADR-0004 |
| 06: MCP interfaces | ADR-0003 / §5 |
| 07: one CRM | ADR-0006 |
| 07: approval object | ADR-0004 |
| 07: kill switch | ADR-0005 |
| 07: email/SMS ownership | ADR-0006 |
| 07: orchestration hub | ADR-0006 |

## Uncertainty
- Rubric scores are INFERENCE (judgment), and the inputs are published above so they can be challenged.
- Peer FACT claims were not re-verified on the web this pass, except the DBOS license (MIT, already verified in round one) and the HumanLayer deprecation (taken from 05, which tagged it FACT).
- The ntfy license is marked UNKNOWN in the integration doc and must be verified before adoption.
