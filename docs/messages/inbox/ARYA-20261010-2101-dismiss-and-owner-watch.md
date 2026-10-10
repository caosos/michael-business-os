# Owner-requested next workflow: dismiss unwanted inventory and keep real potentials

Michael's current request: "Yeah, dismiss unwanted ones. And then I want them replaced with other potentials". He also wants the system to remember which listing he says he has already bid on and keep that visible.

Existing Agent01 coordinator: reconcile existing queue to avoid duplicate feature work, then assign the next bounded serial task AFTER current A57 acceptance correction and existing A50. Do not interrupt active work or create a parallel coordinator/worker. This message does not directly dispatch a specialist.

Source reviewed in live artifacteda3eee:
- market_prefs.act persists dismissed IDs, but rank hides only when suggestions enabled.
- market_routes applies rank only to checked results; unchecked section bypasses dismissal.
- No per-item undo/hidden list exists; reset clears saves/likes too.
- All eligible cache results are rendered, not a fixed recommendation pool. No new inventory is fetched on dismiss.

Bounded task:
1. Dismiss by stable listingID across reload/restart/navigation, checked and unchecked surfaces, regardless of ranking/suggestion toggle. Keep other preferences intact.
2. Individual Undo plus a clear hidden/dismissed list so a user can recover one listing without resetting all saves/likes. Preserve filters and source provenance.
3. After dismiss, show remaining real eligible cached potentials where available, still respecting strict price/location/category/condition/exclusions. Never refill with out-of-filter, unknown-as-known, fictional or duplicated listings. If eligible inventory is exhausted, say so honestly; do not imply new fetch or guaranteed replacement.
4. Focused tests including toggle, both result sections, restart, individual undo, strict-filter invariant, remaining-real-inventory and exhausted-state. Actual desktop/mobile screenshots and real interaction evidence on final committed isolated staging artifact.

Serial follow-on, not one large combined task: owner-reported bid/watch tracking. FIRST inspect existing ledgers/models/UI and reuse an appropriate existing record path instead of a parallel datastore. A locally recorded "I bid on this" must be explicitly owner-reported, separate from live GSA account synchronization, current auction status or bid placement. Keep tracked listing accessible even when discovery filters change, clearly separated from filtered discovery. Return the smallest supported implementation scope/dependency after inspection. Never infer a bid from Save alone.

No private owner bid amounts, ceilings, budgets or personal financial examples in GitHub. No external bids/purchases, GSA sign-in/sync, new source/cachefetch, paid usage or new credentials. Source/staging first; use existing bounded release review after acceptance, do not deploy an unreviewed change or repeat A58. Report ACK/queue/actualSTART separately.
