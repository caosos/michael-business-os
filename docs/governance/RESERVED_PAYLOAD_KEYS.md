# Reserved payload key names for comms.* and publish.* (E-16)

**Audience:** drafting lanes (06 comms, 07 marketing) and Agent 01's planners.
**Source of truth:** `policy/policy.v1.json` → `recommendation_actions` (policy `2026.10.07-w1.9`).

A *binding* offer (OFFER, COUNTER, BUY) must use `offer.*` or `purchase.*`. To make that impossible to get wrong, the PDP denies a `comms.*` or `publish.*` request that *looks* binding. The check is on **key names only**, case-insensitive. Values are never scanned.

| List | Where it is matched | Names |
|---|---|---|
| `binding_payload_keys` | **Top level** of the payload only (any value, even `false`) | `offer`, `offer_amount`, `offer_usd`, `counter`, `counter_offer`, `bid_amount`, `binding` |
| `binding_payload_keys_any_depth` | **Any depth** (the unambiguous amount names) | `offer_amount`, `offer_usd`, `counter_offer`, `bid_amount` |

- **Allowed:** `{"meta": {"binding": false}}`, `{"meta": {"offer": "see flyer"}}`, `{"notes": {"counter": "n/a"}}`. These are nested generic names, so they pass.
- **Denied:** `{"offer": 850}` or `{"binding": false}` at the top level, and `{"meta": {"offer_amount": 850}}` at any depth. The reason is `BINDING_UNDER_COMMS:<names>` or `BINDING_UNDER_PUBLISH:<names>`.
- **A real offer** goes on `offer.<email|sms|message>.send` / `.counter`, where all of these keys are fine.

**Pin your planner** (a unit test in your lane):
```python
from mbos_governance.spine_adapter import binding_key_violations
assert not binding_key_violations(gov, "comms.email.send", draft_payload)   # [] = fine; names listed = would be denied
```
It returns `["POLICY_UNREADABLE"]` if policy cannot be read, and `[]` for capabilities other than `comms.*` and `publish.*`.

**Trade-off (INFERENCE, stated openly):** a binding offer hidden under a nested *generic* name, such as `{"details": {"offer": 850}}`, is not caught by key names alone. The residual protection is Michael's review, since every `comms.*` message is tier 0 and needs his YES on the exact payload. Widening the any-depth list is a data change.
