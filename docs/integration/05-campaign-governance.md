# Campaign governance (E-17, ADR-0013 §9)

- **Owner:** Agent 05
- **Contract:** `campaign.schema.json` (Agent 01, A-26 @ `c18cabc`), vendored byte for byte and sha-pinned.
- **Data:** `policy/policy.v1.json` → `campaigns` (policy `2026.10.07-w1.10`).
- **Code:** `src/mbos_governance/campaigns.py`, `ActionGateway.propose(..., campaign=)`, `spine_adapter.campaign_decision`.
- **Tests:** `tests/test_e17_campaigns.py`.

A campaign is data describing standing demand. **It authorises nothing.**

| Autonomy level | Governance |
|---|---|
| `WATCH_ONLY` | No action may be requested (`no_action`). Notify only. |
| `RECOMMEND` | No action may be requested (`no_action`). Suggest an offer. |
| `ASSISTED_DEAL` | May **draft** only `offer.*` and `comms.*` requests, through the existing path: **tier 0, step-up, Michael's YES on the exact payload hash.** |
| `BOUNDED_AUTOPILOT` | **Denied: `AUTOPILOT_NOT_AUTHORIZED`**, even with valid limits. |
| Unknown or malformed level | **Denied, fail closed** (`CAMPAIGN_LEVEL_UNKNOWN`). |

Other denials:
- the campaign is not ACTIVE (paused, fulfilled, expired or cancelled)
- the campaign is schema-invalid
- the requested capability is outside `offer.*` / `comms.*` (a campaign cannot BUY, publish, pay or commit in this release)
- the cost exceeds the campaign's `max_price_usd`

## How a campaign request cannot skip approval
1. `propose(ar, caller, campaign=…)` decides against the policy above. A rejected request is terminal, and nothing can be approved on it (the gateway and lane D both refuse).
2. A campaign-sourced request is **tainted** (`untrusted_inputs_present`, tier forced to 0). Step-up is therefore required on the YES, and the campaign is recorded in the `POLICY_DECIDED` receipt (`details.campaign`).
3. Structurally, nothing reaches `approved` except Michael's YES through the `approver` role. The gateway role cannot approve (database privilege), and `auto_approved` is unreachable (tier is pinned 0, no delegation). The guard (G1–G8) then re-checks the approval, expiry and payload hash before anything runs.

## Making it looser later
The policy schema pins these rules (`BOUNDED_AUTOPILOT` stays denied, the `ASSISTED_DEAL` tier and step-up, the unknown-level behaviour). Enabling autopilot needs a later explicit Michael decision, a schema change reviewed by Agent 05 and Agent 01, and a migration. Editing the data alone makes the policy unavailable, and the gateway then denies everything.

## For Agent 01's campaign engine
```python
d = spine_adapter.campaign_decision(gov, campaign, capability="offer.email.send", cost_usd=450)   # plain JSON; fail closed
if d["decision"] == "require_approval":
    res = gov.action_gateway.propose(areq, caller, campaign=campaign)    # re-decided, tainted, recorded
```
