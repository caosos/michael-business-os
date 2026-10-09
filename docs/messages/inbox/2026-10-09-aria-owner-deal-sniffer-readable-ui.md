# OWNER INPUT — Deal Sniffer / Michael Business OS: simple visual status and decisions

Date: Friday 2026-10-09 CDT
Source: owner's direct instruction in the MANAGING WORKLOAD ChatGPT project.
Class: OWNER_INPUT + TASK_REQUEST (presentation and interactive operator usability).
Target: Agent 01 coordinator; delegate to existing UI specialist lane 06 if appropriate, not a new agent.

## Owner's words
"This is how I want the Deal Sniffer to be presented, like that. It's easy to read and interact with."

The reference is the clean ChatGPT-style status and action view with prominent small green check marks for actually verified items, short bold headings, plain-language paragraphs and exact next actions. No wall of terminal text, giant technical tables or long generic progress narratives. Also the owner supplied two sample Morning Money Hunt reports (Oct 8 and Oct 9) ranking auction flips and paying service leads, with estimated net margins and honest uncertainty. The reports are **examples of information structure**, not confirmed deal prices or authorization to bid or contact sellers.

## Implement through existing live Operator UI at port 8766
1. Make the owner landing screen glanceable with 3–5 compact **sections/cards**: DONE (verified receipts with check icon), WORKING (real active job), BLOCKED (clear blocker and exact owner action), OPPORTUNITIES (best likely cashflow from live evidence), and NEXT (one primary click).
2. Each opportunity card: natural title, location/source link, clear YES/MAYBE/PASS as evidence warrants, purchase+all-in costs, realistic resale or service quote, *conditional* net and $/hour when calculable, confidence, missing verification, and one next action. Differentiate confirmed actual earnings from simulated examples, unverified bids or speculative estimates. Don't represent the Oct 8/9 reports as verified live deals.
3. Make decisions click-driven in existing UI, accessible on mobile and desktop (Approve, Hold, Pass, More details or whatever controls are already supported), provide a short plain-language explanation, and keep PIN/owner authorization boundaries. Do not invent button actions.
4. Use restrained monochrome/high-contrast styling with small green success icons, meaningful red/amber attention only for real blockers, readable type and ample spacing. Do not use large colorful badges everywhere. Prioritize usability before cosmetics. Show top 3 priorities and keep the rest collapsible, where supported.
5. Respect current P1 bug fixes F-126/127 etc. Don't replace working operator flows or reset the data; first check actual lane 06 UI status and dependencies. Create one bounded task with acceptance and regression tests; **do not derail active bug repairs**.
6. At acceptance, present a visually testable operator view using real local UI components and representative clearly labeled test data, plus screenshots or UI tests if feasible. Verify every displayed DONE is receipt-backed, and every interactive action produces the actual intended state transition. No claims of new real money earned unless receipts prove so.
7. Keep Agent 01's automatic wake permission issue separate: no broad Bash allow rule, no bypass of a permission blocker, no new host changes. You may proceed with owner-approved non-host UI work on normal authorized lanes.

Record this in the canonical backlog, ACK with corresponding `docs/messages/acks/<message-id>.md`, give a receipt and report actual status. Do not require owner to relay the GitHub message to you.

No purchases, spend, external contact, deploy, or live execution authorized.
No action without a receipt. No receipt without provenance.
