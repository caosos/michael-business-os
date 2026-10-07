# Decision

ADR-0005 — Governance control plane: Action Gateway + PDP + execution guard, merged PANIC, two spend ledgers

Status: ACCEPTED (2026-10-06, Agent 01). It adopts Agent 05's ADR-05-001 with changes. The dollar and cash limits are owner decisions (`docs/status/MICHAEL_DECISIONS.md` #1). Until he sets them they default to deny / dry-run.

## Context
Agent 05 designed a PEP/PDP control plane. Agent 01 designed an atomic PANIC and an LLM cost gateway. Each design covers gaps in the other:
- 05 does not cut egress, does not drain queues, and does not control LLM spend.
- 01 has no execution guard, no budget reservation and no fail-closed rule.

## Decision
1. **Adopt 05's Action Gateway** as the only path to any effector. Agents hold no effector credentials. Policy is default-deny, payloads are hash-frozen, and every step writes a receipt.
2. **The execution guard runs 7 checks before every effector call (05 §13):**
   1. Approval is valid.
   2. Approval has not expired.
   3. `payload_hash` still matches.
   4. The idempotency key has not been used.
   5. Budget is reserved.
   6. Grant constraints are met.
   7. The kill switch is clear.

   We add an eighth: `effector_response.dry_run` is forced to true while `SYSTEM_MODE=round_one|mvp`.
3. **PDP.** Start with a thin in-process policy table: category × tier × thresholds as data in Postgres, versioned, with every decision recorded as `POLICY_DECIDED`. The table sits behind a stable `decide(action_request) → {allow|deny|require_approval, tier, policy_decision_ref}` interface. OPA or Cedar (both Apache-2.0) can replace it without changing callers. **Biscuit and SPIFFE/SPIRE are deferred.** INFERENCE: on one host with one operator, OpenBao-scoped short-lived credentials per agent give most of the benefit at a fraction of the operational load. Revisit if a second host or external agents appear.
4. **Tiers 0–3 per 05 §5**, enforced in the ActionRequest schema:
   - Irreversible actions, money, purchases and external commitments are always tier 0.
   - Any untrusted input forces tier 0.
   - First contact with a new counterparty is tier 0.
   - Quiet hours run 20:00–08:00, and are never broader than TCPA's 8am–9pm window in the recipient's local time.
5. **Merged PANIC (C9; rubric 81.0 vs 72.5 for freeze-only):**
   - **L1, per agent:** revoke that agent's OpenBao lease and gateway token.
   - **L2, per capability:** freeze one capability or category in the PDP table.
   - **L3, global:** set `system_state=FROZEN`, revoke all OpenBao leases, set the egress proxy to deny-all, set LiteLLM budgets to 0, and cancel queued DBOS workflows that have not started (status `cancelled_by_freeze`). Calls already started are logged as "in-flight at freeze" and are not retried.
   - **Properties:** the switch fails closed if its state is unreadable. It has out-of-band triggers: an Operator UI button and a host-local CLI, plus a Telegram command if that channel is adopted. A dead-man switch is optional (Michael decision P3).
6. **Two spend ledgers, both enforced outside the model:**
   - **LLM spend:** LiteLLM virtual key per agent, hard daily cap, per-call `max_tokens`, and a circuit breaker. Because LiteLLM resets budgets only about every 10 minutes, caps are set conservatively.
   - **Real-world spend:** 05's budget ledger. It reserves on approval, then commits or releases. Reservations are atomic so parallel approvals cannot overshoot. It fails closed, a soft cap triggers confirmation, a hard cap denies, and irreversible actions never auto-retry.
7. **Unowned areas are now assigned to 05 for round two:** sandbox policy (gVisor baseline, self-hosted E2B for model-generated code), the egress allow-list, and governance observability (alerts on FREEZE, budget breach, INJECTION_SUSPECTED).

## Evidence
- 05 `agent-05-governance.md` §1–13, §17 (28 acceptance tests, all adopted into the integration doc §8).
- 01 research §1 and §11. FACT: OWASP LLM 2026 ranks prompt injection #1 and excessive agency #3.
- Rubric scores are in integration doc §3.

## Risks
- A home-grown PDP can drift. Mitigation: policy as versioned data, the 05 test suite, and the OPA swap path.
- Without SPIFFE, agent identity is weaker. Mitigation: one host, per-agent Unix users and Postgres roles, short-lived OpenBao leases.

## Reversibility
Medium. The gateway pattern is foundational, while the PDP engine and identity layer are swappable behind interfaces.

Coordinator review required: NO. 05 must confirm the merged PANIC and the deferral of Biscuit/SPIFFE in round two.
