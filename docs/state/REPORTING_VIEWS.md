# Reporting views (D-03)

- **Owner:** Agent 04
- **Schema:** `mbos`, defined in `state/migrations/0004_views_grants.sql` and `0005`
- **Who can read them:** every role with SELECT, including `agent_read` (`mbos_reader`)
- **Source of truth:** all views read the authoritative tables. Nothing is cached or materialised, so a view can never disagree with the ledger.
- **Integrity:** the receipts underneath are the ADR-0010 MBOS-RH-1 chain. Check it with `python -m mbos_state verify-chain`.

| View | Answers | Columns | Notes |
|---|---|---|---|
| `v_pipeline_by_lane` | How many items sit in each state, per lane? | `lane` (flip / service), `state`, `items`, `last_change` | Daily operator glance. Lanes are equal (ADR-0007) |
| `v_hold_backlog` | Which requests has Michael parked, and since when? | `action_request_id`, `item_id`, `category`, `capability`, `expires_at`, `approval_id`, `held_at`, `hold`, `hold_until`, `held_for` | Only requests whose **latest** decision is HOLD and whose status is `held`. HOLD never auto-executes; the DBOS workflow owns the wake timers |
| `v_approval_latency` | How long do decisions take? | `approval_id`, `action_request_id`, `item_id`, `category`, `decision`, `requested_at`, `decided_at`, `latency` | `requested_at` is the first `APPROVAL_REQUESTED` receipt, or else the request's `created_at` |
| `v_pnl_by_item` | What did each item actually make? | `item_id`, `lane`, `category`, `state`, `revenue`, `total_cost`, `net_profit`, `hours`, `outcomes` | Sums of `outcomes.realized.*`. The LEARN input for predicted-vs-actual is `outcomes.predicted_vs_actual` |
| `v_budget_reservations` | Real-world money reserved, committed and released | `reservation_id`, `ts`, `category`, `currency`, `action_request_id`, `reserved`, `committed`, `released`, `outstanding` | 05 budget ledger. LLM spend is separate (`llm_spend`) |
| `v_a7_live_effects` | Any non-dry-run effect? | `seq`, `receipt_id`, `type`, `action_request_id`, `effector_response` | **Must stay empty.** It is also blocked by CHECK constraints on `receipts` and `effector_calls` |
| `policy_current` | The policy in force per key | all `policy` columns | No row means the PDP denies |
| `v_receipt_documents` / `v_item_documents` / `v_action_request_documents` / `v_approval_documents` / `v_provenance_documents` / `v_outcome_documents` | Contract-shaped JSON (A10) | `doc` | Item reference arrays are derived from the ledger here, never stored |

Examples:

```sql
SELECT * FROM mbos.v_pipeline_by_lane ORDER BY lane, state;
SELECT action_request_id, hold_until, held_for FROM mbos.v_hold_backlog ORDER BY held_at;
SELECT decision, percentile_cont(0.5) WITHIN GROUP (ORDER BY latency) FROM mbos.v_approval_latency GROUP BY decision;
SELECT lane, sum(net_profit) FROM mbos.v_pnl_by_item GROUP BY lane;
```

Test: `state/tests/test_views.py` covers every view against a mixed flip/service history, and also checks that the read-only role can read them.
