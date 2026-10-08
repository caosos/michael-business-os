# Receipt: D-27 (gate the item edge AWAITING_APPROVAL -> APPROVED)

- Timestamp: 2026-10-08
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue row D-27; finding in `docs/receipts/2026-10-08-d26a-workflow-login-no-approver.md`; `state/migrations/0002_domain.sql` (`items_before_write`).
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only.

## Built
- `state/migrations/0022_item_approved_gate.sql`: `items_before_write` is 0002 verbatim plus a gate. Moving an item to APPROVED needs
  (1) a role of approver, gateway or mbos_owner (otherwise 42501), and
  (2) an `APPROVAL_DECIDED` receipt for this item with decision YES or MODIFY, recorded after the item last entered AWAITING_APPROVAL (otherwise MB005). An approval from an earlier cycle, or a NO, does not count.
- Test: `test_item_approved_edge_needs_approval_receipt_and_role` in `state/tests/test_workflow_login.py`.

## Acceptance
- FACT: as the real `mbos_dbos` (gateway + agent_write): APPROVED without an approval is refused (MB005); still refused after a NO; after the owner login records a YES, the normal path works (`mbos_dbos` takes APPROVED, chain verifies).
- FACT: health `cd state && .venv/bin/python -m pytest`: 283 passed, 1 skipped, 0 failed.

## Limits
- INFER: the gateway (mbos_dbos) may take the edge once the owner's receipt exists, per the task wording "owner/gateway path". An agent_write-only login can never take it.
- INFER: the receipt check is per item, not per action request; for items with several pending requests any YES/MODIFY since entry counts.
