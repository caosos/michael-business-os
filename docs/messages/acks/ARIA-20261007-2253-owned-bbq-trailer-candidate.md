# ACK: ARIA-20261007-2253-owned-bbq-trailer-candidate

- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARIA-20261007-2253-owned-bbq-trailer-candidate.md`
- **Classification:** OWNER_INPUT + OWNED_ASSET + TRAINING_SIGNAL. **Disposition: TASKED** (intake done; economics and UI queued). Acked by Agent 01, 2026-10-09.
- **Authority check:** evaluation/planning only. No purchase, seller contact, spending, cutting/fabrication or listing publication was done or enabled.

## Mapping (no one-off subsystem)
Owned inventory rides the existing inventory/intake/card/economics model:
| Requirement | Where |
|---|---|
| Represent the trailer as owned inventory; inspection intake once photos arrive | **A-45 DONE:** `config/intake/owned_trailer.v1.json` (12 photo angles and 17 questions, safety-relevant first); answers keep a basis; `verified` cannot be set by intake |
| Sunk basis vs new cash vs total basis vs incremental value | **C-30 (lane 03):** decisions use incremental cash from today; the ~$300 purchase is recorded as historical/sunk and excluded from every path's net and ROI |
| Five paths: KEEP, MINIMAL REHAB FLIP, THEMED VALUE-ADD FLIP, CONVERT, SELL AS-IS/PART OUT | **C-30:** same fields per path (incremental cash, hours, risk, seasonality, days to cash, profit per incremental dollar and per hour, finished-resale range, personal-use value) and one recommendation |
| FACT vs INFERENCE on the Little Rock to Conway tow | recorded as `seller_stated` (what Michael said); the engine may only treat it as INFERENCE about running gear, never as roadworthiness, structure, bearings, suspension, lighting or title |
| Economics fields listed in the message | all named in C-30 (`owned_asset`, historical basis, incremental cash, as-is value, rehab ranges, hours, seasonality, risk, alternate use, keep-vs-flip); anything not supplied stays UNKNOWN, no invented rehab costs |
| UI to add and compare | **F-34 (lane 06)** after C-30 |

Next for Michael: when convenient, send the photos listed in the intake spec; nothing is blocked until then, and the system will say exactly which inputs are UNKNOWN.
