# Existing acceptance clarifications; no parallel task

Apply these bounded corrections through the existing serial lane06 state-filter/acceptance work, preserving any active worker. Do not create another worker or duplicate F61.

F61 review at e54e27a:
- auction_labels computes highBidAmount + aucIncrement. This is an ESTIMATED next bid from the cache, not a verified next minimum from the current auction page. Label the calculation estimated and as-of the cached source timestamp, with current live minimum unverified. The stale cache already differs from the observed live GSA379280 page; proxy/reserve rules may affect the actual accepted minimum. Do not imply the calculation guarantees bid eligibility.
- New labels currently appear only in market_view.render_card, the list view. Verify the owner's primary gallery surface also communicates the current bid vs estimated next bid and reserve Yes/No/Unknown/amount undisclosed without ungrounded claims. Reuse the upcoming desktop/mobile staging screenshots to prove the visible result; no separate redesign or capture loop.
- Reject non-finite numeric bid/increment values rather than displaying infinity. Keep unknown opening minimum honest when no current bid is present.

Canonical trailer guideline clarification (docs only): light-duty trailers are NOT categorically excluded. They may be appropriate when condition, verified capacity, total cost and supported repair/resale margin fit the intended use. The rule is to visually inspect and compare like-for-like, not to require heavy-duty construction. Do not include private purchase ceilings, budgets or resale estimates.

Preserve F61 numeric-ID correction, state-filter scope, existing Save/strict filters and A57 repair. No live8766 reload, new source fetch, paid overage, purchase/bid or extra implementation lane. Report actual source changes, tests and screenshot evidence separately from docs adoption.
