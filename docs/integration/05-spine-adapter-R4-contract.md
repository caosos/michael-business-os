# A-03 handoff: the Agent 05 governance adapter and the R4 contract

- **From:** Agent 05 (E-10)
- **To:** Agent 01 (A-03)
- **Date:** 2026-10-07
- **Code:** `src/mbos_governance/spine_adapter.py`
- **Tests:** `tests/test_e10_spine_adapter.py` (15 tests). They drive the adapter through your `mbos.interfaces` @ `8c3e4fd` on lane D @ `14bd690`.

## 1. Wiring
```python
from mbos_governance import PolicyStore
from mbos_governance.spine_adapter import build, reconcile
from mbos_governance.hooks import DbosCancelHook, EgressPolicyHook, LiteLLMBudgetHook

POLICY = "policy/policy.v1.json"
hooks_policy = PolicyStore(POLICY)
gov = build({"agent_write": DSN_DBOS, "gateway": DSN_GATEWAY, "approver": DSN_DBOS, "policy_admin": DSN_POLICY},
            POLICY,
            panic_hooks=[DbosCancelHook(DBOS), EgressPolicyHook("var/egress_policy.json", hooks_policy),
                         LiteLLMBudgetHook("var/litellm_keys.json", hooks_policy)])
components = Components(..., gateway=gov.gateway, kill_switch=gov.kill_switch, pdp=gov.pdp)

@DBOS.scheduled("*/5 * * * *")          # E-05: stuck claims (TTL = policy.execution.claim_ttl_seconds)
@DBOS.workflow()
def reconcile_claims(scheduled, actual):
    reconcile(gov.action_gateway)
```
- **`build()` connections.** It takes one DSN for every role, or a DSN per role. The gateway writes on its **own** `gateway` connection and ignores the `engine` argument. This lets you drop `gateway` from `mbos_dbos` later (lane D RECOMMENDATION).
- **`Gateway.execute(engine, areq_id, approval_id)`** returns a `GuardResult`:
  - check names are yours (`approval_valid` … `dry_run_mode`, mapped from G1–G8)
  - `frozen` is True when G7 failed, or when the request ended `cancelled_by_freeze`
  - a mismatching or stale `approval_id` gives `approval_valid=False` and leaves the request untouched
- **A5 replay.** A second call returns the original `effector_response` with `ok=True`.
- **DBOS recovery.** If `gateway_step` is re-run after the process died *during* execution, the adapter settles that request by provider lookup (E-05) and never re-sends:
  - found: `ok=True`, "reconciled after crash"
  - not found: `ok=False`, `PROVIDER_NOT_FOUND`
- **`KillSwitch.is_clear(conn, capability=, agent_id=)`** calls `mbos.panic_blocks` in **your** transaction. The category is resolved from policy data, so `category:<x>` freezes apply. Any error returns `(False, …)`.
- **`PolicyDecisionPoint.decide(full areq)`** returns a `PolicyDecision`. An unreadable policy, a malformed draft or an unknown capability all give `deny`. It never returns `allow`, because the wave-one schema forbids it.

## 2. R4: who writes what (binding for `spine_d.begin_act` / `finish_act`)

**The gateway (05) writes, and the spine must NOT write:**

| ActionRequest edge | Receipt(s) |
|---|---|
| `approved → executing` (plus the `mbos.effector_calls` claim) | `ACTION_EXECUTING` |
| `executing → executed` | `ACTION_EXECUTED`, `BUDGET_COMMITTED` |
| `executing → failed` / `executing → cancelled_by_freeze` | `ACTION_FAILED`, `BUDGET_RELEASED` |
| `approved → expired` (G2) / `approved → failed` (G3) | `ACTION_FAILED` (or `POLICY_DECIDED` with no approval), `BUDGET_RELEASED` |
| (no edge) guard refusal | `ACTION_FAILED` with `effect=none` / `POLICY_DECIDED` |
| reservation at YES and at G5 | `BUDGET_RESERVED` |
| L3 cancellation `approved → cancelled_by_freeze` | `KILL_SWITCH_CHANGED` (lane D `panic_set`) |

**The spine (01) writes:**
- Item transitions only: `AWAITING_APPROVAL → APPROVED → ACTING → ACTED | FAILED`, plus HELD and ARCHIVED.
- Michael's decision through `mbos.record_approval` (role approver): `pending_approval|held → approved|rejected|held`, with `APPROVAL_DECIDED`.
  - Propose the MODIFY successor first.
  - The gateway's `record_approval` also refuses an invalid YES and notes it as `POLICY_DECIDED`. If you record decisions yourself, apply the same checks (step-up, approver, channel, scope, hash) or route through `gov.action_gateway.record_approval`.
- Proposals through `propose_action`, or better through `gov.action_gateway.propose(ar, caller, untrusted_texts=…)`. The gateway's version adds the E-04 secret scan and the injection tripwire, and does the classification itself.
- Expiry of a request **without** a decision: `pending_approval|held → expired` with `POLICY_DECIDED` (your `expire()`). This stays yours.

**Concrete changes to `spine_d.py`:**
- **`begin_act`:** keep the Item moves (→ APPROVED → ACTING). **Remove** `_status(conn, areq, "executing", "ACTION_EXECUTING", …)`.
  - FACT, tested: if the spine moves the request to `executing` itself, the gateway refuses with `G1:STATUS_NOT_APPROVED:executing` (`test_r4_spine_writing_executing_itself_breaks_execution`).
- **`finish_act`:** **remove** both `_status(...)` calls (`ACTION_EXECUTED` and `ACTION_FAILED`). Map `guard.ok` to Item `ACTED`, and anything else to Item `FAILED`. Item receipts may cite `guard.reason` and `guard.effector_response`. The authoritative action receipts are already written by the gateway: exactly one `ACTION_EXECUTING` and one `ACTION_EXECUTED` per action (`test_r4_one_receipt_per_edge_when_spine_follows_contract`).
- **`set_kill_switch`:** replace it with `gov.action_gateway.engage_panic` / `release_panic`. Release runs as approver, and L3 engage runs the hooks.

## 3. Facts and limits
- **FACT:** 15 E-10 tests pass, and the full suite (233 tests) passes on PG16 with lane D @ `14bd690`.
- **INFERENCE:** the dry-run provider record is in-process. After a real process restart, a crashed dry-run claim reconciles to `failed` (not found), which is the safe direction. A live effector must answer `lookup` from the provider.
