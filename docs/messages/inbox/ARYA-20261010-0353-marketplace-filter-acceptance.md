# Make the real Marketplace useful for Michael
ID: ARYA-20261010-0353-marketplace-filter-acceptance
Created: 2026-10-10 03:53 UTC
From: Michael via Arya
Type: OWNER_PRODUCT_CORRECTION
Project: Deal Sniffer / Michael Business OS

Michael just inspected the live Marketplace and is frustrated that its 154 results include an unaffordable hydraulic crane and whiteboards in Laredo, Texas. He explicitly wants an adjustable price-range control plus location filtering to narrow useful opportunities. The example "$1 to $20,000" describes a control's range, NOT a spending authorization or his budget. He does not want demo/training navigation in his normal working view. This is income-first product acceptance, not a new dashboard project.

Priority: reconcile with existing F49 implementation/verification and prior UI directives, then make the current real-listing workflow usable. Do not duplicate completed F49 work. The separate ARYA-20261010-0328-f49-verification message still defines its evidence/reload boundary.

Required outcomes:
1. Working minimum/maximum price controls, with an accessible slider/range option and precise numeric inputs. Preserve entered filters across the relevant navigation. Show applied filters plainly. For auctions, label current bid versus asking price and unknown all-in costs; never imply current bid is final purchase cost.
2. Reliable location and radius around Conway, Arkansas / ZIP 72032, editable by Michael. Radius must actually constrain known-distance results. Put unknown/unresolved locations in a separately labeled optional area rather than silently treating them as local matches. Do not invent coordinates or nationwide coverage.
3. Michael's normal view should emphasize relevant repairable trailers/equipment and actionable local opportunities, with clear editable category/keyword controls. A broad inventory browsing mode can exist, but do not dump unrelated faraway lots as his default useful deal shortlist. Distinguish documented working-capital settings from verified cash; do not assume the $20,000 example is a budget.
4. Remove demo/training navigation and fictional records from the normal owner workflow. Preserve deliberate testing behind a separate explicit route; do not destroy historical records.
5. Explain GSA as government surplus auctions, cache freshness, and image/login limitations in plain language. Show verified original-listing links. No fabricated photos, login bypass or credential capture.
6. Existing search/saved actions must be operable and visibly readable; inspect actual browser behavior, not HTTP success alone. Diagnose the faded Search control in the owner's screenshot rather than assume it is disabled.

Acceptance: demonstrate an actual browser search for relevant trailer/equipment listings near Conway, show changing min/max price and radius changes the correct result set, include out-of-radius and unknown-location tests, preserve current-bid caveats and no fabricated valuations. If no qualifying listing exists, show zero honestly. Verify no fake TV/demo content appears on normal routes. Provide screenshots, exact artifact SHA, commands/tests, source/cache timestamps, and explicit code-versus-live status.

Keep existing Agent 01 ownership, resource limits, security controls and receipt discipline. No purchases, seller contact, new paid services, credentials, arbitrary integrations or Linode/other-project changes. Do not silently reuse exhausted live reload approval; return a consolidated narrow gate for any required live change. Continue authorized staging/code/testing work.

Automatic pickup is still an essential separate reliability task in the owner account. Reconcile current interactive session with the registered watchdog target without launching competing coordinators or bypassing account permissions. Publish a matching ACK at docs/messages/acks/ARYA-20261010-0353-marketplace-filter-acceptance.md with the next concrete step and actual blocker if needed. Do not call delivery or implementation done without evidence.
