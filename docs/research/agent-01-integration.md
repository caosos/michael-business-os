# Michael Business OS: Integrated Round-One Architecture (Agent 01)

**Round One: research and design only.** Nothing has been deployed, contacted, purchased or published.

This document merges the seven round-one research efforts into one system. **Relationship to `ROUND_ONE_SYNTHESIS.md`:** the synthesis (Aria / Agent 01 lane) is the authoritative executive summary. This document is the detailed engineering record behind it: the conflict register with rubric scores, the frozen machine-readable contracts, ADRs, the acceptance suite and the per-specialist gap lists. Where they differ, the synthesis wins and this document was aligned on 2026-10-07 (approval surface = Operator UI; Python is not an owner decision; owner decisions = `docs/status/MICHAEL_DECISIONS.md`). `agent-01-coordinator.md` remains the technology survey.

**Date:** 2026-10-06 · **Author:** Agent 01 (chief coordinator / systems architect)

**Inputs** (all read-only via `git show`; full provenance in `docs/receipts/2026-10-06-round-one-reconciliation.md`):

| Agent | Branch | Commit |
|---|---|---|
| 02 | agent-02-opportunity | `da52612` |
| 03 | agent-03-economics | `b032676` |
| 04 | agent-04-state | `be6aed9` |
| 05 | agent-05-governance | `5ee191d` |
| 06 | agent-06-communications | `c7af3bb` |
| 07 | agent-07-marketing | `68dd3e8` |

Tags: **FACT** (verified in a peer report or on the web), **INFERENCE**, **RECOMMENDATION**, **UNKNOWN**.

---

## 0. Executive summary

1. **Scope (Michael, 2026-10-06; ADR-0007).** The OS serves two equal lanes:
   - **value-add FLIPS:** trailers, mowers, generators, welders, compressors, tools, commercial and mechanical equipment, project vehicles, and other undervalued assets
   - **paid SERVICES:** mobile repair, equipment repair, drywall, assembly, handyman work, smart-home installs, and related technical services

   Neither cars nor home services narrow the system. One Item envelope covers both, with `type ∈ {flip, service}`.
2. **The architecture held up under cross-examination.** Agent 04 independently reached the same core rule: a Postgres spine where the write, its receipt and the outbox commit in one transaction. Agents 05, 06 and 07 all adopted "no action without a receipt" and YES/NO/MODIFY/HOLD.
3. **17 conflicts were found and resolved** (§3). The big ones:
   - C1: SQLite → **Postgres**
   - C2: Temporal / n8n → **DBOS**
   - C4: CRM as system of record → **Postgres, with Twenty as a projection**
   - C5: three receipt shapes → **one merged Receipt v1**
   - C9: two kill-switch designs → **one 3-level PANIC**
   - C10: LLM spend vs real-world spend → **two ledgers**
4. **Contracts are frozen** as validated JSON Schema in `docs/research/contracts/` (ADR-0004), with worked examples for a flip (trailer) and a service (drywall).
5. **One build plan:** a unified 24-hour MVP (one flip vertical, dry-run only), a 1-week path that adds the service lane and full governance, and a single acceptance suite of about 70 tests with owners (§8).
6. **What's next:**
   - Michael's owner decisions are the five in `docs/status/MICHAEL_DECISIONS.md` (§11). None blocks the dry-run MVP.
   - Every specialist has an exact round-two gap list (§10).

---

## 1. Integrated stack (final for round one)

| Layer | Decision | License | Source of the decision |
|---|---|---|---|
| Runtime | Podman + Quadlet + systemd | Apache-2.0 | 01 |
| Spine | **PostgreSQL 16** + pgvector (rebuildable index only) | PostgreSQL | 01 + 04 (ADR-0001) |
| Durable backbone | **DBOS Transact** (Python) — Temporal = scale-out | MIT | 01 vs 05 → ADR-0002 |
| Reasoning | LangGraph / Pydantic AI **inside single steps only**; approvals never via `interrupt()` | MIT | 01 + 05 caveat |
| Tool boundary | MCP; every side-effect through the **Action Gateway** | MIT SDKs | 01 + 04 + 05 + 06 → ADR-0003/0005 |
| Ledger | Insert-only, **hash-chained** receipts (`seq`, `prev_hash`, `row_hash`), lifecycle events | — | 04 storage + 05 events + 01 same-txn → ADR-0004 |
| Artifacts | Content-addressed sha256 store (FS → Garage/SeaweedFS; **not MinIO CE**) | Garage AGPL / SeaweedFS Apache-2.0 | 04 |
| Policy (PDP) | Versioned policy table behind OPA/Cedar-compatible `decide()` | — (OPA/Cedar Apache-2.0 later) | 05 → ADR-0005 |
| Secrets | OpenBao (dynamic leases) + SOPS (bootstrap) | MPL-2.0 | 01 + 05 (Vault BUSL rejected) |
| LLM spend | LiteLLM per-agent virtual keys, hard caps | MIT | 01 |
| Real-world spend | 05 budget ledger (reserve → commit/release, fail-closed) | custom | 05 |
| Kill switch | 3-level PANIC (L1 agent / L2 capability / L3 global) | custom | 01 + 05 → ADR-0005 |
| Sandbox / egress | gVisor baseline; self-hosted E2B for model-gen code; default-deny egress proxy | Apache-2.0 | 01 (assigned to 05 for round two) |
| Observability | Langfuse (agent traces/cost) + Prometheus/Grafana/Alertmanager; OTLP | MIT / Apache-2.0 (Grafana AGPL) | 01 |
| Backups | pgBackRest PITR + nightly `pg_dump` + replicated artifact store; restore drills | MIT | 01 + 04 |
| Discovery | `SourceAdapter` MCP tools run by DBOS cron; tiered access per ADR-02-0202 | various (beware AGPL `ai-marketplace-monitor`) | 02 |
| Scoring | 03 gates-first hybrid engine, `scoring-config.json` (`2026.10.0`) as single source | custom | 03 |
| Comms effectors | Telnyx (voice/SMS, official MCP), Postmark (email), Vapi/Retell hosted voice → LiveKit/Pipecat later | proprietary SaaS / Apache-2.0 / BSD-2 | 06 |
| Marketing | Drafts only → 06 effectors; Cal.diy (MIT) booking; Umami (MIT) analytics; static site; manual-assist lane | MIT etc. | 07 |
| CRM UI | Twenty as **optional one-way projection** | AGPL-3.0 | 04 + 07 → ADR-0006 |
| Approvals UX | **Operator UI** (dashboard, opportunity cards, YES/NO/MODIFY/HOLD queue, step-up); Telegram optional later | — | ADR-0006 + synthesis Agent F |
| Alerts (one-way) | ntfy | Apache-2.0 / GPL-2.0 (UNKNOWN exact; verify) | 02 |
| Connector (optional) | n8n **connector only** (or Activepieces MIT) | Sustainable Use (fair-code) | 02/07 → ADR-0006 |
| Language | Python 3.12+ / Pydantic v2 | — | ADR-0008 (technical; per synthesis) |

---

## 2. Integrated architecture diagram

```
                     ┌───────────────────────────────────────────────────────────┐
                     │ MICHAEL   Operator UI queue: YES · NO · MODIFY · HOLD      │
                     │           (+ step-up for money / irreversible / rules)     │
                     │           ntfy = one-way alerts only                       │
                     └──────────────▲──────────────────────────┬─────────────────┘
                     approval request│ (payload_hash shown)     │ Approval row (append-only)
┌────────────────────────────────────┴──────────────────────────▼──────────────────────────┐
│ GOVERNANCE CONTROL PLANE (05 + 01; the agent processes cannot modify it)                  │
│  PDP policy table (category×tier×limits, versioned) ── decide() → allow/deny/approve      │
│  ACTION GATEWAY + EXECUTION GUARD (8 checks: approval valid, not expired, payload_hash     │
│     match, idempotency unused, budget reserved, grant ok, kill-switch clear, DRY-RUN mode) │
│  Spend: LiteLLM (LLM $, per-agent keys) │ Budget ledger (real-world $, reserve/commit)     │
│  PANIC  L1 agent: revoke lease │ L2 capability freeze │ L3 global: FROZEN + revoke all     │
│         leases + egress deny-all + LiteLLM=0 + cancel unstarted workflows (fail-closed)    │
└────────────────────────────────────┬──────────────────────────────────────────────────────┘
                                     │ only path to effectors
┌────────────────────────────────────┴──────────────────────────────────────────────────────┐
│ DBOS DURABLE BACKBONE (cron, queues, exactly-once steps, durable waits)                    │
│                                                                                            │
│ DISCOVER ─► NORMALIZE ─► RESEARCH ─► SCORE ─► RECOMMEND ─┬─ PASS → ARCHIVED (receipt)       │
│  02 SourceAdapters  02→Item v1  02/03     03 config      ├─ MAYBE → RESEARCH (cheapest      │
│  (flip + service)                                         │          decisive evidence)/digest│
│                                                           └─ YES → ActionRequest(s)          │
│                                                                      │ PDP tier              │
│                                         APPROVAL GATE (durable wait) ◄┘                      │
│                                         YES→ACT · NO→close · MODIFY→new areq · HOLD→park     │
│                                              │                                              │
│  ACT via gateway ─► effector (06 comms │ 07 drafts→06 │ 04 state writes) ─► RECEIPT          │
│                                              │                                              │
│  OUTCOME (04 store; 07 attribution) ─► LEARN (03: Brier/MAPE → config version bump)         │
└───────────┬───────────────────────────────────────────────────────────────┬─────────────────┘
            │ MCP (stdio / Streamable HTTP)                                    │ LLM calls
   ┌────────┴──────────┬──────────────────────┬────────────────────┐   ┌─────┴──────┐
   │ 04 State MCP       │ 06 Comms effectors   │ 02 SourceAdapters  │   │  LiteLLM    │
   │ (only write path)  │ Telnyx · Postmark ·  │ API>email>JSON>    │   │  → Langfuse │
   │                    │ Vapi/Retell          │ browser>manual     │   └────────────┘
   │                    │ consent/DNC ledger   │ (gVisor, egress    │
   │                    │                      │  allow-list)       │   optional: n8n
   └────────┬───────────┴──────────────────────┴────────────────────┘   connector (sandboxed,
            ▼                                                            per-call lease)
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ POSTGRES SPINE: items · action_requests · approvals · receipts (insert-only, hash-chained)  │
│   · provenance · outcomes · lessons · parties/leads/attribution · policy · budget_ledger    │
│   · outbox · pgvector (rebuildable)   ▲ state change + receipt + outbox = ONE transaction     │
└──────────────┬─────────────────────────────────────────────┬───────────────────────────────┘
               │ outbox (one-way)                              │ WAL
        Twenty CRM projection (optional)          pgBackRest PITR + pg_dump → off-box
                                                  artifact store (sha256) replicated
```

---

## 3. Conflict register (scored with the §7 comparison framework of `agent-01-coordinator.md`)

**Rubric weights** (max 90): provenance ×3, safety ×3, durability ×2.5, ops burden ×2, license ×2, maintenance ×1.5, capability ×1.5, interop ×1.5, reversibility ×1. The hard gate (it must be able to emit receipts and provenance) is applied first.

| # | Conflict | Parties | Options scored | Ruling | ADR |
|---|---|---|---|---|---|
| C1 | Datastore | 02 (SQLite) vs 01/04 | Postgres **84.0** · SQLite 60.0 (fails same-txn under concurrent writers: INFERENCE) | Postgres | 0001 |
| C2 | Durable backbone | 01 (DBOS) vs 05 (Temporal) vs 02/07 (n8n) | DBOS **81.5** · Temporal 74.5 · n8n 51.0 (fails gate as SoR) | DBOS; Temporal scale-out | 0002 |
| C3 | n8n role | 02, 07 | — | Optional sandboxed connector only | 0006 |
| C4 | CRM as SoR | 07 vs 01/04 | Postgres SoR + Twenty projection **78.0** · Twenty SoR 59.0 | Postgres SoR | 0006 |
| C5 | Receipt shape | 01, 04, 05, 06 (07 defers) | — (merge, not choose) | Receipt v1 | 0004 |
| C6 | IDs | 04 bigint/uuid vs 05 prefixed ULID | — | Prefixed ULID public + `seq` internal | 0004 |
| C7 | Verdict vocabularies | 03 YES/MAYBE/PASS, 05/07 YES/NO/MODIFY/HOLD, 06 approve/edit/reject | — | verdict ≠ decision; routing rule | 0004 |
| C8 | State machines | 01 Item flow vs 05 ActionRequest status | — | Nested: Item flow ⊃ ActionRequest status | 0004 |
| C9 | Kill switch | 01 atomic PANIC vs 05 3-level freeze | Merged **81.0** · 05-only 72.5 | Merged L1/L2/L3 | 0005 |
| C10 | Cost control | 01 LLM vs 05 real-world | — | Two ledgers | 0005 |
| C11 | Approval channel | 02 ntfy; 06/07 undecided | Telegram 78.0 · web UI 77.5 · ntfy 58.0 (tie) | **Operator UI** primary (higher on provenance and safety; synthesis lane F); Telegram optional; ntfy alerts only | 0006 |
| C12 | Outbound ownership | 06 vs 07 | — | 06 owns all effectors; 07 drafts | 0006 |
| C13 | Per-mile cost & distance rule | 02 ($0.65–0.70, rings) vs 03 ($0.46, 0.35 ratio) | — | 03 config is single source; 02 `profit_per_mile` display-only; values = Michael (P1) | 03-001 |
| C14 | 03 internal inconsistency | 03 | — | §17.1 trailer YES at $62/h vs $65 rule; AT-14 locks it. 03 must fix rule **or** test | 03-001 |
| C15 | Unowned areas | none | — | Sandbox, egress, observability → 05 in round two | 0005 |
| C16 | Evidence-tag vocabulary | 03 FACT/INFER/REC/UNK | — | Canonical long form; short alias only inside 03 vendor blocks | 0004 |
| C17 | ADR numbering | 01/04/07 ADR-0001 vs 03/05/06 ADR-001 | — | Global registry + `ADR-<agent>-<n>` aliases | INDEX.md |
| — | Business domain | 06 (cars) vs 07 (home services) vs 02/03 (both) | — | **Michael: flips + services** | 0007 |

Per-dimension scores (0–5) for each scored option are kept in this round's receipt so anyone can reproduce them.

---

## 4. Frozen contracts (ADR-0004; `docs/research/contracts/`)

| File | What it is |
|---|---|
| `item.schema.json` | Envelope with `type` flip/service, a per-type category enum, `sources[]`, `normalized` (02), `economics` (03 blocks, `$ref`-pinned), `research[]`, `scores{scorecard_id, inputs_hash, scorecard}`, `recommendation{verdict YES/MAYBE/PASS, proposed_actions[], reversibility}`, and **ID references only** to action requests, approvals, receipts, outcomes and provenance |
| `action-request.schema.json` | 05's ActionRequest. Schema-enforced: irreversible, money, purchase, external commitment and untrusted input all force **tier 0** |
| `approval.schema.json` | YES/NO/MODIFY/HOLD. `payload_hash_seen` must match the request. MODIFY requires `modifications.new_action_request_id`. HOLD requires `hold{hold_until, wake_on[], renotify_after, escalate_after}` and **never auto-executes**. NO requires `reason` |
| `receipt.schema.json` | Lifecycle event with `type` enum. Requires `provenance_ids` (minItems 1), `idempotency_key`, `prev_hash` and `row_hash`. Action events require `action_request_id`, `capability` and `payload_hash`. EXECUTED/FAILED events require `approval_id` and `effector_response`. Also carries `llm_cost` and `budget_effect`, plus a typed `details` field (06 comms, 07 marketing) |
| `provenance.schema.json` | Must resolve to a source URI + time, a model + version + prompt hash, an approval ID, or a tool + version |
| `outcome.schema.json` | Predicted vs actual per economics field (03 LEARN), realized P&L, and 07 attribution |
| `examples/*.json` | Flip trailer (YES, held by Michael), service drywall (MAYBE, needs photos), action request, HOLD approval, receipt, provenance, outcome |
| `validate_contracts.py` | Validates all schemas and examples, and checks negative invariants |

**Item state machine:**
`DISCOVERED → NORMALIZED → RESEARCHING ⇄ SCORED → RECOMMENDED → AWAITING_APPROVAL → {APPROVED → ACTING → ACTED → OUTCOME_RECORDED → LEARNED} | HELD | REJECTED`. `ARCHIVED` (from PASS or NO) and `FAILED` can be reached from any state.

Every transition writes an `ITEM_STATE_CHANGED` receipt in the same transaction.

---

## 5. Ownership map (round two)

| Area | Owner | Consumes | Produces |
|---|---|---|---|
| Contracts, backbone, integration, acceptance suite, ADR registry | **01** | everything | ADR-00NN, `contracts/` |
| Sources, `SourceAdapter`s, raw→Item mapping, dedup, both lanes | **02** | Item v1 | `sources[]`, `normalized`, `raw_ref` |
| Economics, scoring config, comps rules, LEARN calibration | **03** | `normalized`, `research[]`, outcomes | `economics`, `scores`, `recommendation`, config bumps |
| Postgres DDL, ledger triggers, State MCP (only write path), artifacts, projections, backups | **04** | contracts | tables, `verify_chain`, restore drills |
| Gateway, PDP, guard, budget ledger, PANIC, sandbox, egress, governance alerts | **05** | ActionRequest | `POLICY_DECIDED`, freeze events |
| All outbound effectors, consent/DNC ledger, approval-channel UX, templates | **06** | approved ActionRequests | `ACTION_EXECUTED` with `details.kind=comms` |
| Content and campaign drafts, attribution capture, listings (manual-assist lane), resale listing copy for flips | **07** | Items, outcomes | ActionRequests (drafts), attribution |

---

## 6. Adopt vs custom (updated)

**Adopt:**
- PostgreSQL, pgvector, DBOS, LangGraph/Pydantic AI, MCP SDKs
- LiteLLM, Langfuse, Prometheus/Grafana
- OpenBao + SOPS, gVisor, self-hosted E2B, pgBackRest
- Telnyx, Postmark, Vapi/Retell (hosted phase)
- Twenty (optional), Cal.diy, Umami
- ntfy (alerts)

**Custom.** These are the actual product:
1. Item v1 and both state machines
2. Hash-chained receipt ledger with same-transaction enforcement
3. Action Gateway, execution guard and PDP policy table
4. Budget ledger
5. 3-level PANIC
6. SourceAdapters and the normalization mapping
7. 03's scoring engine
8. Operator UI approval queue (YES/NO/MODIFY/HOLD)
9. LEARN loop
10. Consent/DNC ledger
11. Manual-assist packet generator (07)

---

## 7. Unified build paths (round-two build plans; nothing is built in round one)

### 7a. 24-hour MVP: prove the loop and the invariant on one flip vertical, dry-run only
| Hours | Work | Lead |
|---|---|---|
| 0–4 | Postgres 16 + pgvector in Podman. DDL for `items, action_requests, approvals, receipts, provenance, outcomes, outbox, policy, budget_ledger`. Insert-only and hash-chain triggers. Roles `agent_read`/`agent_write`/`gateway` | 04 |
| 4–8 | DBOS app with the Item workflow, Pydantic models generated from `contracts/` | 01 |
| 8–12 | eBay Browse + Craigslist (Conway/Little Rock) `SourceAdapter` MCP tools (read-only), normalized to Item v1 | 02 |
| 12–15 | 03 engine v0 against `scoring-config.json` 2026.10.0. Must pass AT-1 (replay) and the AT-12/13 gates | 03 |
| 15–19 | ActionRequest, PDP table (everything tier 0), gateway with all 8 guard checks, **dry-run effector**, LiteLLM daily cap, L3 PANIC stub (FROZEN flag, fail-closed) | 05 |
| 19–22 | Minimal Operator UI queue (opportunity cards, YES/NO/MODIFY/HOLD); HOLD as a durable wait plus timer | F (Operator UI lane) |
| 22–24 | Crash-resume drill, `verify_chain`, one end-to-end walkthrough, `RUNBOOK.md` | 01/04 |

**MVP acceptance:** tests A1–A10 in §8 pass.

### 7b. 1-week path: both lanes, full governance, real operations hygiene
- **Day 2.** Service lane: one inbound lead source (website form or referral intake) as `type=service`, using 03 service weights and 07's attribution capture.
- **Day 2–3.** Governance:
  - 05's full budget ledger (reserve, commit, release)
  - tier 0 only, per MICHAEL_DECISIONS #5 (no delegation during the MVP)
  - PANIC L1/L2/L3 for real: OpenBao leases, egress proxy deny-all, LiteLLM budget zeroed
  - fail-closed behavior, plus the Operator UI and CLI triggers
- **Day 3.** Observability: Langfuse on every LLM call; Prometheus/Alertmanager alerts for stuck workflows, DLQ, budget breach, FREEZE and INJECTION_SUSPECTED; ntfy for alerts.
- **Day 4.** Security: OpenBao + SOPS, gVisor for adapters, the egress allow-list, and E2B only if a model-generated-code path exists.
- **Day 4–5.** Communications stays a **mocked adapter** in the first implementation wave (synthesis). It emits `details.kind=comms` receipts with `dry_run=true`, and the consent/DNC ledger schema is in place. 06's three live scenarios wait for MICHAEL_DECISIONS #4.
- **Day 5.** Backups: pgBackRest PITR off-box, nightly `pg_dump`, and a restore drill followed by `verify_chain`.
- **Day 6.** LEARN: an outcome recorded on one sold flip and one completed service updates 03's Brier/MAPE and proposes a config bump (which itself needs approval).
- **Day 6–7.** Optional: the Twenty projection, the web step-up approval page, and a GovDeals/HiBid adapter (only if Michael approves the ToS posture).

---

## 8. Unified acceptance suite

Every test has an owner. Round-two builders must make them pass. Source suites are adopted by reference.

**A: Core invariant and MVP** (owner 01/04):
- **A1.** Each transition writes its state change and its receipt in one transaction. A fault injected between them leaves **both or neither**.
- **A2.** UPDATE or DELETE on `receipts`, `approvals` or `provenance` is rejected by a trigger, even for the `agent_write` role.
- **A3.** `verify_chain` passes, and fails after a byte is tampered with (05 §17 tamper test).
- **A4.** Every receipt's `provenance_ids` resolve under `provenance.schema.json`'s anyOf rule.
- **A5.** Killing the process mid-ACT, then restarting, resumes at the step with no duplicate effector call (idempotency key).
- **A6.** YES executes the frozen payload. NO archives with a reason. MODIFY creates a new `areq` with `derived_from`. HOLD survives a restart, wakes on its condition, re-notifies after the TTL and **never auto-executes**.
- **A7.** In round one and the MVP, 100% of effector receipts have `dry_run=true`. Audit query: zero exceptions.
- **A8.** The LiteLLM cap blocks further calls once exceeded, regardless of agent behavior.
- **A9.** The L3 PANIC fails closed. With the flag unreadable, the gateway denies everything.
- **A10.** Every stored Item, ActionRequest, Approval, Receipt, Provenance and Outcome validates against `contracts/` (contract conformance).

**B: Governance** (owner 05). All 28 tests in `agent-05-governance.md` §17. Highlights:
- each of the 11 categories is blocked without approval
- expired approval is refused
- payload-hash mismatch is refused
- 100 parallel approvals never exceed the cap
- crash reconciliation causes no re-send
- a timed-out money call queries the provider before any retry
- the comms agent cannot call `money.*`
- an injected listing yields at most a tier-0 proposal
- outbound secret scan
- plus **B29:** L3 PANIC cuts egress (a test call to an allow-listed host fails) and cancels unstarted workflows

**C: Economics** (owner 03). AT-1 to AT-21 in `agent-03-economics.md` §18, **after the AT-14 fix (C14)**. Plus:
- **C22:** every scorecard stores `inputs_hash`, and replay reproduces the same hash.
- **C23:** the flip and service worked examples in `contracts/examples/` score consistently with their recorded scorecards.

**D: State** (owner 04):
- **D1.** A restore drill to a fresh host passes, and `verify_chain` passes afterwards.
- **D2.** A reboot test: everything comes back under systemd with no manual steps.
- **D3.** The pgvector index is dropped and rebuilt with identical query results (it is a rebuildable index).
- **D4.** The Twenty projection is rebuilt from the outbox with no drift.

**E: Communications** (owner 06). Thresholds Agent 06 must confirm or tighten:
- **E1.** The disclosure script is present in 100% of calls.
- **E2.** Every send has a consent and DNC check recorded.
- **E3.** No send happens outside 8am–9pm in the recipient's local time, or outside the stricter quiet hours.
- **E4.** STOP is honored in under 1 minute.
- **E5.** Voice p95 response latency is ≤ 1.0 s (INFERENCE target; 06 to set).
- **E6.** Every outbound has a receipt with `provider_msg_id` (100% completeness).
- **E7.** An out-of-band negotiation always escalates to Michael.

**F: Discovery** (owner 02):
- **F1.** Every Item has at least 1 `sources[]` entry with a `raw_ref`.
- **F2.** The duplicate rate after dedup is below 2% on a 7-day sample (INFERENCE target).
- **F3.** A repeated 403/429 triggers the L2 freeze for that source.
- **F4.** No collector touches a do-not-automate source (ADR-02-0202).

**G: Marketing** (owner 07):
- **G1.** No publish, post or send happens without an approved ActionRequest.
- **G2.** Every lead carries an attribution record.
- **G3.** Every review request complies with Google's 2026 review policy: no gating, no incentives.
- **G4.** Manual-assist packets carry content hash, prompt version and model in provenance.

---

## 9. Integration risks (new, from reconciliation)

The original 11 risks in `agent-01-coordinator.md` §11 still stand.

1. **Vendor-block coupling.** Item v1 `$ref`s 03's schemas verbatim. *Mitigation:* 03 versions its `$id`, and 01 re-pins.
2. **Receipt volume.** Recording every lifecycle event produces about 5–8 receipts per executed action. *Mitigation:* 04's monthly partitioning. INFERENCE: this is trivial at the expected volume, but 02 has not supplied volume per day (an UNKNOWN).
3. **The legal path is the critical path** for any live outbound: TCPA AI-voice rules, A2P 10DLC (which needs an EIN), all-party recording consent, and UETA/E-SIGN rules on binding offers. *Mitigation:* all outbound stays dry-run until the P2 decisions; tier 0 is permanent for offers and commitments.
4. **Gray-zone source ToS** (internal JSON endpoints on GovDeals, HiBid, etc.). *Mitigation:* ADR-02-0202 tiers, the do-not-automate list, and the L2 per-source freeze. Michael decides P2.
5. **AGPL contamination.** BoPeng `ai-marketplace-monitor` (AGPL) is reference-only and must not be vendored. Twenty and Garage are used unmodified as services.
6. **HumanLayer is effectively deprecated** (05: FACT, the repo is "pretty much all deprecated"). The 01 survey's "consider HumanLayer" is withdrawn; the custom Operator UI approval queue replaces it.
7. **Unverified assumptions in 03's thresholds** (most are REC/UNK). Wrong $/hr targets would mis-rank everything. *Mitigation:* the P1 decisions plus LEARN calibration.
8. **Two kinds of "receipt".** An action receipt is different from a financial receipt document (04). *Mitigation:* financial documents are artifacts referenced by `artifact_hashes`.

---

## 10. Round-two gap requests (exact; each agent answers in its branch)

These lists feed the synthesis build lanes:

| Build lane | Specialist input |
|---|---|
| A Core Platform | 01 |
| B Discovery | 02 |
| C Economics | 03 |
| D State/Receipts | 04 |
| E Governance | 05 |
| F Operator UI | 06 approval UX + 07 |
| G QA/Integration | §8 acceptance suite + `validate_contracts.py` |

06's live comms and 07's publishing are research-only or mocked in wave one.

| Agent | Must deliver |
|---|---|
| **02** | (1) Estimated items/day for the top-10 sources, flip and service lanes separately. (2) Per-source field mapping raw → Item v1 `normalized`/`sources[]`, with a `raw_ref` retention rule. (3) The data source for each 03 input: comps (sold), DOM, active-listing count, listing age, auction end. (4) Service-lane lead sources with access method and cost per lead. (5) Re-target to Postgres; drop n8n as the backbone; ntfy is alerts only. (6) Cost per source (Apify, proxies) in $/month. |
| **03** | (1) Resolve C14: change §12.4 or AT-14, and state which. (2) Add the missing formula inputs to the schemas: `market_buy_median`, `active_comparable_listings`, `listing_age_hours`, `auction_ends_in_hours`, `evidence_quality`, `requires_license_he_lacks`, `cost_to_quote`, plus a skill-proficiency store. (3) Add `lead_quality` to flip (or document its absence) and `buy_fees` to service. (4) Add `inputs_hash` and `scorecard_id` per ADR-0004. (5) Write worked examples for at least 3 flip categories (trailer, mower or generator, `project_vehicle`) and at least 3 service categories (drywall, smart-home install, equipment repair). (6) Specify the config-bump approval flow for LEARN. |
| **04** | (1) Adopt Receipt v1 field names, prefixed ULIDs and `seq`. (2) DDL for `approvals`, `outcomes`, `lessons`, `action_requests`, `policy` and `budget_ledger`. (3) Twenty projection mapping: fields, direction (one-way) and rebuild procedure. (4) Reporting views: pipeline by lane, P&L by item, approval latency, HOLD backlog. (5) RPO/RTO proposal for Michael. (6) A 1-week plan. (7) Remove the custom "resume position" tables; DBOS owns that. |
| **05** | (1) Category × tier × threshold matrix as **data** (CSV/JSON), with defaults set to deny. (2) Confirm the merged PANIC, and specify the egress-cut and queue-drain mechanics. (3) Sandbox policy: which tools run under gVisor and which need E2B. (4) Egress allow-list per adapter and effector. (5) LLM-spend policy via LiteLLM (per-agent daily caps). (6) Accept or contest deferring Biscuit and SPIFFE. (7) A 24h/1-week build slice for the gateway. |
| **06** | (1) Generalize from used cars to all flip categories (seller Q&A per category) and to service-customer intake, scheduling and follow-up. (2) Approval UX spec for the Operator UI (lane F): card layout, MODIFY form, HOLD presets, expiry, re-notify. Optional Telegram quick-decide. (3) Template registry with versioning and pre-approval. (4) Numeric rate and consent rules: messages per contact per day, TCPA 8am–9pm local time, DNC scrub cadence. (5) `inputs_hash` and `idempotency_key` on sends. (6) Pass/fail thresholds for E1–E7. (7) Confirm ownership of 07's sends. |
| **07** | (1) A Campaign entity: budget, schedule, audience, variants, linked to Item and ActionRequest. (2) A reversible/irreversible classification for every `action_type`. (3) Numeric spend and volume caps per channel. (4) Map attribution to `outcome.schema.json`. (5) Content provenance: content hash, prompt version, AI-content labeling policy. (6) TCPA and 10DLC compliance for SMS review requests, via 06. (7) Accept Postgres as system of record with Twenty as a projection. (8) Resale-listing drafts for **flips** (Marketplace, Craigslist, eBay) in the manual-assist lane. |
| **All** | Answer in FACT/INFERENCE/RECOMMENDATION/UNKNOWN. Validate any example payloads with `docs/research/contracts/validate_contracts.py`. Object in `AGENT_STATUS.md` → "Needs coordinator review" if a ruling here is wrong; the objection is then scored with the §7 rubric. |

---

## 11. Michael's owner decisions: see `docs/status/MICHAEL_DECISIONS.md` (authoritative)

Only business-policy decisions go to Michael. Reversible technical choices are settled by the coordinator. These were settled technically, not by Michael: Python, Postgres, DBOS, MCP, n8n at the edge only, no CRM required for the MVP, and the Operator UI approval surface.

**None of the five decisions blocks the dry-run MVP.** Each is mapped to where it lands in the system:

| MICHAEL_DECISIONS # | Decision | Where it lands | Default until decided |
|---|---|---|---|
| 1 | Cash-at-risk per flip and in total | 03 `capital_and_risk.*` in `scoring-config.json` + 05 budget ledger hard caps | Conservative: 03's REC $1,500 per deal / $800 max loss, real-world spend deny-all (dry-run) |
| 2 | Time-value floor and target ($/Michael-hour) | 03 `time_value.*` → YES/MAYBE/PASS thresholds | 03's provisional $40 floor; $65 flip / $75 service targets; calibrated by LEARN |
| 3 | Higher-risk source access | ADR-02-0202 tiers + L2 per-source freeze; per-source enable flag | Official/sanctioned sources only; no evasion after a block |
| 4 | Outbound AI calling/texting and counsel | 06 effectors (ADR-0006), tier 0 permanent for offers | **Disabled**; mocked adapters only |
| 5 | Approval delegation | 05 tiers 1–3 / standing rules (`approval.scope=standing_rule`) | **No delegation**: everything at tier 0 |

Other items that eventually need owner input are not needed now. They come up at the gate where they matter:
- EIN/entity status, needed for A2P 10DLC
- business name, service area and Google category, needed for marketing go-live
- RPO/RTO (coordinator default: RPO 15 min / RTO 4 h)
- dead-man switch (default off until set)

---

## 12. Remaining UNKNOWNs
- Real volume per day per source (02). This drives the partitioning and broker decision. Current INFERENCE: Postgres plus DBOS queues are enough.
- TCPA status of AI-voice calls to sellers who listed publicly (06 says it needs an attorney).
- Whether Google's Local Posts API v4.9 is still live (07).
- Parity between Twenty's self-hosted MCP and its cloud version (04).
- ntfy's exact license (verify before adoption; alerts only, so low risk).
- Whether LiteLLM's roughly 10-minute budget-reset granularity is acceptable at the chosen caps. It is mitigated with per-call `max_tokens` and a circuit breaker.
