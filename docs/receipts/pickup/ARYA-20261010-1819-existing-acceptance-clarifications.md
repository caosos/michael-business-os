# Pickup receipt: ARYA-20261010-1819-existing-acceptance-clarifications

- **Status:** COMPLETED (docs-only adoption; dry-run). Source/code changes: NONE by this pickup.
- **Docs adopted:**
  - `docs/product/DEAL_SNIFFER_START_HERE.md` section 13a: added the rule that light-duty trailers are not categorically excluded; inspect and compare like-for-like; no private ceilings, budgets or resale estimates included.
  - `docs/status/READY_QUEUE.md` row F-61 (existing row, no new row/worker): appended the three acceptance clarifications (estimated next bid labelled as-of cache timestamp with live minimum unverified; verify gallery surface via existing staging screenshots; reject non-finite bid/increment and keep unknown opening minimum honest), plus preserve-list and no-live-reload/fetch/spend limits.
- **Code work remaining (lane 06, existing serial F-61 worker, then F-136):** the `auction_labels` estimate wording, gallery-surface verification, non-finite rejection, and their tests/screenshots. Not implemented or verified here; no source files were inspected or changed.
- **Not done / not claimed:** no live :8766 reload, source fetch, spend, bid/purchase, contact, or other-project change. No new worker created; F-136 row and A-57 untouched.
- **Tests:** none applicable (docs only); 0 code files changed.
- **Remaining blockers:** none for docs; code acceptance pending in F-61.
