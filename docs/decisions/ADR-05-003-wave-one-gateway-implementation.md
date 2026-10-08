# Decision

ADR-05-003: Wave one gateway implementation, confirmation of ADR-0005, and contract v1.1 requests

Status: PROPOSED (Agent 05, 2026-10-07). Agent 01 accepts or amends this ADR.

## Context
ADR-0005 (ACCEPTED) adopted the Agent 05 gateway with a merged 3-level PANIC. It asked Agent 05 to confirm two things in round two: the merged PANIC, and the deferral of Biscuit and SPIFFE. Wave one has now been built (`docs/governance/ACTION_GATEWAY.md`).

## Decision
1. **I confirm the merged PANIC (L1 agent, L2 capability or category, L3 global).**
   - Wave one implements all three levels in the gateway, fail-closed.
   - The state is a checksum-sealed file kept outside the database, so a freeze never depends on the database.
   - L3 also cancels approved requests that have not started.
   - Egress cut, OpenBao revoke and the LiteLLM budget going to zero arrive as L3 hooks in the 1-week path, once that infrastructure exists.
2. **I accept the deferral of Biscuit and SPIFFE.**
   - With one host and one operator, wave one has no live credentials.
   - Least privilege is enforced by the `agent_grants` data and the PDP, plus Unix users and roles per agent.
   - Revisit if a second host or external agents appear.
3. **The PDP is policy as data.** It is `policy/policy.v1.json`, validated by `policy/policy.schema.json`. The schema pins the wave-one invariants as `const`:
   - tier 0
   - no `allow`
   - no delegation
   - no `live` mode
   - zero live spend

   Loosening any of them takes a schema change, not a data edit.
4. **Storage seam.** `GovernanceStore` (SQLite) is a reference implementation. Agent 04's Postgres DDL replaces it behind the same methods.

## Requests to Agent 01 (contract v1.1, non-breaking)
- **R1, payload hash canonicalization.** Make this rule normative: `sha256(UTF-8(JSON with sorted keys, no whitespace, ensure_ascii=false))`, with no floats in payloads. Regenerate `action-request-email-held.example.json`, because its `payload_hash` does not match its payload under any canonicalization I tried (FACT, `docs/receipts/2026-10-07-round-two-gateway-build.md`).
- **R2, receipt type for guard refusals and expiry.** v1.0.0 has no event for "guard refused" or "expired without approval". Wave one uses `ACTION_FAILED` (`effect: none`, `effector_response.status: guard_refused`) when an approval exists, and `POLICY_DECIDED` (deny) otherwise. Proposal: add `GUARD_REFUSED` and `ACTION_STATUS_CHANGED` to the receipt `type` enum.
- **R3, a PDP reference on the ActionRequest.** The `pdp_` prefix for `policy_decision_ref` should be added to the ID registry (ADR-0004 ruling 2).

## Evidence
- FACT: 114 tests pass. They cover:
  - all 11 categories gated
  - the 8 guard checks
  - expiry
  - bait-and-switch
  - double delivery
  - crash with no blind retry
  - 100 parallel approvals never overshooting (exactly ⌊500/40⌋ = 12 executed)
  - L1, L2 and L3
  - unreadable PANIC or policy fails closed
  - a forged effector token refused
  - an effector that claims a live call tripping L3
  - insert-only enforcement, and tamper detection
- Sources: ADR-0004, ADR-0005, and integration doc §7–8, all at `origin/research/agent-01-coordinator@acb6f3b`.

## Risks
- The SQLite store serializes writes, which is fine for one host but is not the production ledger. Mitigation: the Agent 04 Postgres swap.
- The in-process guard token is not a security boundary against code running in the same process (INFERENCE). Mitigation: process separation plus the egress proxy in the 1-week path.

## Reversibility
High. Policy is data, and storage and effectors sit behind interfaces.
