# A-18 wiring: exact call sequence (E-14)

- **From:** Agent 05
- **To:** Agent 01 (A-18)
- **Code:** `mbos_governance.spine_adapter`
- **Tests:** `tests/test_e14_wiring.py` (9 tests; one runs real DBOS 3.2)

## 1. At worker start (once per process, in this order)
```python
from dbos import DBOS
from mbos_governance import spine_adapter as sa

DBOS(config=...)                                   # your DBOS config
gov = sa.build(DSNS, None, dbos=DBOS,              # None => production policy from lane D (mbos.policy_current)
               egress_file="var/egress_policy.json",
               litellm_file="var/litellm_keys.json")
#        ^ wires the three L3/L1/L2 hooks: DbosCancelHook(DBOS), EgressPolicyHook, LiteLLMBudgetHook
components = Components(..., gateway=gov.gateway, kill_switch=gov.kill_switch, pdp=gov.pdp)

sched = sa.schedule_reconcile(gov, DBOS, crontab="*/5 * * * *")   # 1. BEFORE DBOS.launch(): registers the workflow
DBOS.launch()
sched.activate()                                                  # 2. AFTER launch: creates the persistent schedule
#        "created" | "unchanged" | "replaced"; idempotent across restarts and across workers
```
- `DSNS` is one DSN, or `{agent_write, gateway, approver, policy_admin}`. The DBOS login `mbos_dbos` is a member of `agent_write`, `approver` and (until the gateway runs alone) `gateway`, so a single DSN works.
- **DBOS 3.x note.** Schedules are persistent system-database rows created with `DBOS.create_schedule` after launch. There is no `@DBOS.scheduled` decorator in 3.x, which is why `schedule_reconcile` is two steps.
- The scheduled runs are protected from the L3 cancel hook, so reconciliation keeps working while frozen. It records what already happened and never acts.

## 2. Freeze and release (replace `spine_d.set_kill_switch`)
```python
out = sa.engage_panic(gov, "L3", None, "michael", "incident")        # any actor may engage
#   -> {"state": {...}, "cancelled": [areq...], "hooks": {"dbos_cancel": {...}, "egress_policy": {...}, "litellm_budgets": {...}}}
out = sa.engage_panic(gov, "L2", "money.*", "agent-01-coordinator", "spend anomaly")   # or "category:sms"
out = sa.engage_panic(gov, "L1", "agent-07-marketing", "michael", "misbehaving")

out = sa.release_panic(gov, "L3", None, "michael", "all clear")      # runs as the `approver` role
sa.panic_state(gov)                                                  # {"global", "readable", "revision", "frozen_agents", ...}
```
- **Engage** is one `mbos.panic_set` transaction (state plus a `KILL_SWITCH_CHANGED` receipt).
  - On L3 it also cancels approved but unstarted requests in the same transaction, and releases their reservations.
  - The hooks then run, and their results are receipted in a second `KILL_SWITCH_CHANGED` receipt.
  - A failing hook never blocks the freeze (its entry shows `ok: false`).
  - If the database is unreachable the freeze cannot be written. Then PANIC also **reads FROZEN everywhere**, the call returns `{"error": ...}` instead of raising, and the attempt is journaled.
- **Release** raises in these cases, and everything stays frozen:
  - `GatewayRefused` if the actor is not a policy approver, the reason is blank, or the policy is unreadable
  - the database error if the login lacks the `approver` role
- **Release order.** Loosening hooks (egress allow-list, LiteLLM budgets) run **after** the release committed with its receipt.
- **Hooks never loosen on engage.** Engage can only deny.

## 3. Kill switch inside a workflow transaction
`gov.kill_switch.is_clear(conn, capability=..., agent_id=...)` is unchanged. It reads PANIC in your transaction and fails closed.

## 4. Acceptance
A-18 is a wiring change: replace `set_kill_switch` with `engage_panic` / `release_panic` and register `schedule_reconcile` as above.
