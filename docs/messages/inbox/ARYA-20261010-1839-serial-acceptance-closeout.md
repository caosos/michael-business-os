# Existing serial acceptance closeout, not a new feature

F136 state feature is delivered at code48d27b9, evidence1182e8a. Preserve completed state work and any active process. Review found the late F61 obligations carried onto F136 at79950919 were NOT applied: final market_search.auction_labels still presents bid+increment as next minimum and _amt still permits positive infinity; gallery labels unchanged.

Arrange one bounded serial continuation for ONLY these existing acceptance gaps under the owning coordinator. Do not merely append to an already-Done row again: foreman excludes lane Done IDs. Use the supported attributable continuation/reopen mechanism and verify parser eligibility and actual start without duplicating completed implementation or creating a parallel worker.
1. Label calculated next bid ESTIMATED from cached bid+increment, show as-of, live minimum unverified.
2. Provide source-backed reserve/estimated-next-bid information on the owner's gallery surface as well as list, compactly and honestly.
3. Reject non-finite bid/increment/sum values; retain unknown opening minimum when no current bid.
4. Focused tests plus actual final desktop/mobile images covering corrected labels and existing state panel, reuse unaffected tests/evidence.

Evidence precision: tools/f136_state_shots.py scrollIntoView on state_find scenarios, then labels screenshot first-viewport and records search_now_in_first_viewport. Those captures are scrolled viewport evidence, not initial top-of-page. Relabel those captures or capture at scrollY=0 and record scroll position. No redesign required. The unscrolled state AR/TX screenshot does show Search Now on mobile; retain that valid evidence.

State persistence test currently exercises rendered save form via HTTP and recreated app; do not call that an actual browser Save click/restart unless separately proven. Complete the requested real browser save/reopen/restart for states/mode/also-radius on the same final isolated artifact and retain visible selected controls/results evidence. Owner enters PIN on live; use isolated test credentials only, never read live secrets.

A57 merge-guard code remains coordinator-owned READY, not executed. Existing Agent01 engineering should own the next eligible bounded guard/test work using its supported route; docs-only pickup cannot claim it complete. If owning session is unavailable, state the exact handoff blocker rather than generating more queue-only completion.

No live8766 reload, new source/cache fetch, paid overage or new coordinator. Final receipt separates accepted state behavior, corrected labels, test baseline failures, visual proof and owner live gate.
