# Same A60 acceptance clarification: Hide this listing is NOT learning

Michael clarified: "I don't want it to learn that ... I'm just not interested in that one" and "I want it to have not interested more like this, less like this. That's for it to learn. But it needs to have, like hide this one ... like an X button ... bottom right hand corner ... system remembers that I don't want to see that one again".

Amend the EXISTING A60 item from ARYA-2101, not a duplicate task or worker:
- Distinct X / Hide this listing control at bottom-right of the card, accessible name and keyboard operation. Durable stable-ID hide across restart/filters/ranking toggle/checked+unchecked sections.
- Exact-listing hide MUST NOT train category, title-term preferences, similarity or ranking. Preserve saved/bid-watch records; hide applies to discovery, not deletion of owner history.
- Keep explicit Not interested / More like this / Less like this learning controls separate and label their effect honestly. Existing Not interested currently maps to exact-ID dismiss; reconcile implementation/labels so it is not silently conflated with the new X control.
- Per-item Undo/hidden list restores only that listing, without resetting learned preferences or other saves.
- Preserve existing strict-filter real-inventory refill/exhaustion acceptance and add a test that X leaves all learning weights unchanged. No extra parallel feature.

Photo access context only: Michael wants GSA photos and is willing to log in if an existing supported route permits it. Do not implement account integration, scrape authenticated pages or request/read credentials from this message. Keep verified original-listing links as fallback and report the actual supported access dependency. No bid or external account mutation is authorized.

Same owner session/serial A59/A50→A60→inspection-firstA61 route. No new queue item, live change, fetch, paid usage or coordinator.
