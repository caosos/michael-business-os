# Pickup receipt: ARYA-20261010-2104-a60-hide-versus-learning

- Docs-only coordination; no code, restart, fetch, bid, spend, contact or credentials.
- Amended the existing A-60 row in `docs/status/READY_QUEUE.md` (no new item/worker): distinct bottom-right X hide (not learning, stable-ID durable, preserves saves/bid-watch), separate honest Not interested / More like this / Less like this learning controls, reconcile current Not interested (exact-ID dismiss), per-item Undo restoring only that listing, test that X leaves all learning weights unchanged, strict-filter refill/exhaustion kept.
- Photo access: recorded as context only; no account integration/auth scraping; original-listing links remain fallback; the actual supported access dependency is for the code lane to report.
- A-61 unchanged (still inspection-first, after A-60).
- Tests: none run (docs only).
- Remaining: A-60 implementation by the 01 engineering lane after A-59/A-50; nothing needed from owner now.
