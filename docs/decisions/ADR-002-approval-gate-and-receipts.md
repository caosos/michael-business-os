# Decision

Status: PROPOSED

## Context
An AI communicating and negotiating on Michael's behalf creates legal exposure: under UETA §14 / E-SIGN an electronic agent can form contracts that bind the human user, and the FCC (Feb 2024) treats AI voice as "artificial voice" under the TCPA (consent/identification/opt-out, $500–$1,500 per call/text, uncapped). We must decide the control model that lets the agent act autonomously within limits while keeping binding commitments and legal risk under human control — and how to make every communication auditable ("no action without a receipt; no receipt without provenance").

## Options considered
1. **Full autonomy** — agent calls/texts/negotiates/commits freely. Rejected: binding-contract + TCPA + misrepresentation exposure.
2. **Full manual** — Michael approves every message. Rejected: defeats the purpose; doesn't scale.
3. **Bounded autonomy + approval gate + receipts** — agent acts within a pre-approved price/term band and vetted scripts, but any binding offer/acceptance, out-of-band move, or escalation trigger pauses for human approval; mandatory AI + recording disclosure on every contact; every communication emits a hash-chained receipt.

## Recommendation
Adopt **Option 3**. Specifically:
- **Hard-coded policy limits** (price floor/ceiling, max concessions, allowed hours/topics/volume) — enforced as constraints, not just prompt text.
- **Human-approval gate** before: first outbound contact, any binding offer/counteroffer, scheduling at Michael's location, money commitments, adding a channel, and on any escalation trigger.
- **Mandatory disclosure** opening every contact: automated AI assistant acting for Michael + "this call may be recorded"; treat all calls as all-party-consent.
- **Hash-chained communication receipts** (schema in research §13) for every inbound/outbound message — tamper-evident provenance and the audit trail for compliance + negotiation-liability defense.

## Evidence
- Research: docs/research/agent-06-communications.md (§12 guardrails, §13 receipt schema, §14 legal)
- Receipt: docs/receipts/receipt-04-legal-compliance.md
- FCC AI-voice ruling (Feb 8, 2024); TCPA penalties; UETA §14 / E-SIGN electronic-agent contract formation; CAN-SPAM; A2P 10DLC. Sources cited in receipt-04.

## Risks
- "Solicited inquiry" status of AI-voice calls to sellers is legally unsettled — needs counsel before any outbound calling.
- Over-tight gates slow throughput; band design must be tuned.
- Receipt schema must be reconciled with Agent 04 (CRM/state) and Agent 05 (governance) to avoid divergence.

## Reversibility
High for band/threshold tuning; the approval-gate and receipt-chain principles should be treated as foundational (expensive to retrofit if omitted).

## Coordinator review required: YES
(Approval gate + receipt schema overlap with Agent 05 governance and Agent 04 state; this is a cross-system concern — do not mark ACCEPTED without Agent 01 review.)
