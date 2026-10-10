# Existing owner ledger: auction capital reservations

Type: TASK_REQUEST
To: existing Agent 01 coordinator
Docs/backlog clarification within existing A-61 owner-reported bid/watch planning. No new parallel implementation or worker. Preserve current work and task ordering.

Owner requires auction waiting time and opportunity cost to inform decisions. Generic acceptance criteria only; private balances, bids, budgets and amounts must stay out of this repository:
- An active owner-reported auction bid reserves its potential maximum all-in cost until confirmed outbid/released, withdrawn where actually supported, or won and paid. Do not treat an unverified stale auction status as released funds.
- Keep cash balance, reserved bid capacity, committed purchase cost, repair allowance, and protected bill buffers separate. Never reuse the same available cash for multiple simultaneous bid commitments.
- Show owner-reported versus verified status, as-of time, uncertainty, and expected auction/payment/pickup timing. Waiting time and alternative opportunities belong in the proposal.
- Owner-configurable private values and corrections require a supported owner-local path; report that path when the existing ledger scope reaches implementation. Do not put values in GitHub, fixtures, receipts or public documentation.
- These records and proposals confer no authority to debit an account, place/change/withdraw a bid, buy, contact a seller, or connect banking/auction accounts.

Capture in existing canonical criteria and the existing A-61 owner-ledger backlog rather than creating another engineering queue item. This is requirements adoption only, not a claim that reservation accounting already exists.
