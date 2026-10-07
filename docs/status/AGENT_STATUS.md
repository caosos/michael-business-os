# Agent Status

Agent: 05
Role: Governance / Approval / Security — "controlled autonomy"
Branch: research/agent-05-governance
Worktree: /home/michaelos/business-os-worktrees/agent-05-governance
State: COMPLETE
Current phase: Round One — research & design (no live external actions taken)
Started: 2026-10-06
Last updated: 2026-10-06

## Current objective
Round-One deliverable is complete. Holding for Agent 01 (coordinator) reconciliation
and for Michael's decisions on the open items listed below before any Round-Two build.

## Completed
- Full governance/approval/security architecture design.
- External-tool survey (HITL/workflow, policy engines, capability tokens, identity,
  secrets, prompt-injection references) with URLs, licenses, and activity — verified by
  read-only web research.
- Approval object/schema, delegation model, capability model, kill switch, spend/comms
  limits, receipt/audit schema, idempotency, authority-boundary enforcement.
- Prompt-injection defense design (architectural, not filter-based).
- 28 acceptance tests; threat→control traceability table.
- 2 decision records (ADR-001, ADR-002) and a tooling-survey receipt.

## Findings
Key verified facts (full detail + sources in docs/research/agent-05-governance.md §15):
- **Temporal** (MIT, self-hostable) and **LangGraph** (MIT) give durable pause→resume
  for approval gates out of the box; Temporal uses indefinite Signal-waits + timeout,
  LangGraph uses `interrupt()`+checkpointer (gotcha: node re-runs from top on resume).
- **"AgentGate" is NOT a citable project** — the name is reused across several unrelated
  early-stage repos; no mature standard. Use HumanLayer (noting it has pivoted away from
  the approval product), LangGraph interrupts, Temporal signals as real anchors.
- **OPA/Rego** (Apache-2.0, CNCF Graduated) and **Cedar** (Apache-2.0, formally verified)
  are the strongest fits for the policy decision point. Oso's OSS lib was deprecated
  Dec 2023 — avoid for self-hosting.
- **Biscuit** (Apache-2.0, public-key signed, offline attenuation) is the best modern fit
  for agent capability/delegation tokens; macaroons are the symmetric-key alternative.
- **SPIFFE/SPIRE** (Apache-2.0) for agent workload identity; OAuth2 token-exchange for
  short-lived scoped tokens.
- **Vault is BUSL-1.1 since v1.15 (Aug 2023)** — no longer OSI-open; **OpenBao** (MPL-2.0)
  is the open fork. Dynamic short-lived secrets + encryption-as-a-service keep raw secrets
  out of agent/model context.
- OWASP LLM01, Simon Willison (dual-LLM, lethal trifecta), and DeepMind's CaMeL
  (arXiv:2503.18813) all converge: the model proposes, a non-LLM engine authorizes.
  There is no reliable prompt-level filter — defense must be architectural.

## Decisions made
- **ADR-001 (PROPOSED):** single Action Gateway choke point + external Policy Decision
  Point + execution guard; agents hold no effector credentials; default-deny; everything
  is a receipt. Maps to the standard PEP/PDP/PIP split.
- **ADR-002 (PROPOSED):** adopt Temporal (durable workflow) + OPA/Rego or Cedar (policy) +
  Biscuit (capabilities) + SPIFFE or cloud IAM (identity) + Vault/OpenBao or cloud secret
  manager (secrets); build thin custom gateway/ledger/trust-tagging; borrow (not depend on)
  HumanLayer/OpenAI `needs_approval` patterns for approval UX.
- Core invariant: no world-affecting side effect executes without a matching approved,
  un-expired, un-replayed approval whose payload-hash still matches.

## Unknowns
- Exact current license of any remaining Oso OSS component (lib deprecated).
- Precise Vault BUSL acceptability for our use (OpenBao is the fallback).
- Agent/non-human-identity standards are active but unsettled — SPIFFE+OAuth is the
  defensible-today path.
- No production-grade CaMeL implementation exists — it's a pattern, not a library.
- Final deployment target (self-hosted vs cloud) determines the identity/secrets stack.

## Blockers
None. Round-One scope fully delivered.

## Needs Michael decision
(See research file §18 for full context.)
1. Dollar limits: per-action, per-category/day, per-counterparty, global/month.
2. Comms limits: messages/day per recipient, quiet hours, which categories may ever
   reach delegated (Tier 1+) autonomy.
3. Acceptable step-up auth (2FA) method for approving money/irreversible actions.
4. Approval channel(s): web UI only, or also SMS/email approve-by-reply.
5. Dead-man's switch: auto-freeze if Michael unreachable for N hours? What N?
6. Receipt strength: is hash-chaining enough, or want signed/externally-anchored receipts?
7. Will anyone besides Michael ever approve actions (multi-approver)?
8. Deployment target: self-hosted box vs cloud (drives identity/secrets stack).

## Needs coordinator review (Agent 01)
- ADR-001 and ADR-002 affect the whole system — require cross-agent reconciliation.
- Interface with Agent 04 (state): the receipt/audit event schema and the append-only
  hash-chained ledger must be jointly owned; Agent 05 defines required governance events,
  Agent 04 owns storage. Need alignment on the shared receipt object.
- Interface with Agent 03 (economics): `provenance.score_ref` on each ActionRequest links
  to Agent 03's score — confirm the score object has a stable ID.
- Interface with Agent 06 (communications): comms approval points, first-contact gate,
  quiet hours, consent/recording legal findings must feed the comms capability policy.
- Interface with Agent 01's core flow: the gate sits at "MICHAEL APPROVES → ACT → RECEIPT".

## Files produced
- docs/research/agent-05-governance.md — full Round-One deliverable (architecture,
  schemas, delegation, capabilities, identity, kill switch, limits, receipts, idempotency,
  authority boundaries, prompt-injection defenses, tool survey, 28 acceptance tests).
- docs/decisions/ADR-001-governance-control-plane.md
- docs/decisions/ADR-002-governance-tech-stack.md
- docs/receipts/2026-10-06-governance-tooling-survey.md
- docs/status/AGENT_STATUS.md (this file)

## Next action
Await Agent 01 coordinator review of ADR-001/ADR-002 and Michael's answers to the 8
decisions above. No Round-Two build until scope is authorized.
