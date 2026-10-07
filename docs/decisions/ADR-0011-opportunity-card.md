# ADR-0011: The Deal Sniffer opportunity card

- **Status:** ACCEPTED (Agent 01, technical). The contract change that stores enrichment natively is PROPOSED (ADR-0009 items 10–11).
- **Trigger:** Michael, 2026-10-07: a raw listing plus a score is not enough. The Operator UI must present opportunities the way an experienced buyer/mechanic evaluates them. *The score is for the machine; the explanation is for Michael.*
- **Frozen contracts:** untouched. `card.schema.json` is a NEW file in `docs/research/contracts/`.

## Decision
1. **A card is a derived view, not a new source of truth.** `mbos.card.build_card(item, receipts, action_requests, enrichment)` is pure and deterministic (same inputs → same `card_hash`). It stores nothing and grants no authority. Michael's decision is still `Approval.decision` (YES|NO|MODIFY|HOLD) on an ActionRequest.
2. **Honesty rule: UNKNOWN, never a guess.** Every datum is a value with a basis (FACT|INFERENCE|RECOMMENDATION) and optional provenance, or the literal `UNKNOWN` (with a reason). Malformed lane enrichment degrades to UNKNOWN. The card lists every UNKNOWN path so Michael sees what the system could not establish. Seller intelligence, listing dates, seasonality and model-specific advice are never fabricated.
3. **Recommendation vocabulary (R15).** `CONTACT | OFFER | BUY | COUNTER | HOLD | PASS` presents the *next step* and is derived from the machine verdict plus the live ActionRequest capability: `comms.*`→CONTACT, `offer.*`→OFFER, `offer.*.counter`→COUNTER, `purchase.*`→BUY. `waiting=true` means the action is already in flight ("CONTACT / WAIT FOR RESPONSE"). A PASS resting only on assumptions (`pass_on_priors`) is shown as HOLD, never discarded. OFFER/BUY/irreversible actions show `requires_step_up`. A closed item (outcome recorded) shows PASS ("no further action").
4. **Status timeline (R16).** DISCOVERED → RESEARCHED → SCORED → CONTACT APPROVED → CONTACT SENT → SELLER RESPONDED → NEGOTIATING → QUALIFIED → AWAITING MICHAEL → CLOSED / PASSED, each with a timestamp and the receipt that proves it. A stage appears only if an event source exists. **NEGOTIATING and QUALIFIED have no event source yet** (inbound comms is mocked); they are never invented. They need new events (ADR-0009 item 11).
5. **Activity trail (R17): no invisible autonomous actions.** Every receipt about the Item becomes a row: who (agent), what, why, input provenance, result, receipt id, and the next action. No receipt, no row; no provenance, no receipt.
6. **Mechanic-level content (R18).** Michael is an experienced mechanic. Elementary advice ("check compression/spark/fuel/oil…") is rejected by `validate_card` unless a lane marks it model-specific with a source. A model-specific risk must carry a source or provenance. Lane C owns the content; the card enforces the bar.
7. **Logistics (R19).** Transport is an economic variable, never an automatic rejection. Michael's capabilities are data in `config/operator_profile.v1.json` (trailer_owned=false, borrowed_trailer_possible=true). A deal that requires a trailer stays on the list; `borrowed_trailer_confirmed` is UNKNOWN until a person confirms it with the lender; the system never assumes it.
8. **Enrichment without a contract change (interim).** A lane attaches a block with `spine.record_enrichment(conn, item_id, block, data, provenance_id)`: the block is a content-addressed artifact, cited from `Item.research[]` (`field="card.<block>"`, `source_uri="artifact:<sha256>"`) with the lane's provenance, and receipted. Blocks: `listing_activity`, `seller`, `economics`, `value_add`, `seasonality`, `logistics`, `make_model`, `distance_miles`, `why`. The enrichment is therefore visible in the activity trail.

## Ownership
| Piece | Owner |
|---|---|
| Card contract, builder, text view, enrichment seam, operator profile | 01 |
| `listing_activity` and `seller` blocks (posted/updated/age/relist/stale risk; seller intelligence where the source permits) | 02 |
| `economics` ranges, opening offer, maximum acquisition, `logistics`, `seasonality`, `why` | 03 |
| `value_add` plan and sourced model-specific risk knowledge | 03 (+02 for sources) |
| Rendering in the Operator UI | 06 |
| Card acceptance (no fabrication, lint, completeness) | 07 |
| Offer/purchase policy tiers and caps for the recommendation actions | 05 |
| Read access to enrichment artifacts for the UI role | 04 |

## Contract changes PROPOSED (ADR-0009)
- **Item 10:** first-class Item fields (or a typed `enrichment` object) replacing the artifact convention.
- **Item 11:** events for NEGOTIATING and QUALIFIED (new outcome kinds or an Item sub-state) once inbound communications exist.
- Receipt type `ITEM_UPDATED` for enrichment (today it is `ITEM_STATE_CHANGED` with an unchanged state).

## Consequences
- The Operator UI can show a decision-ready card today, with honest UNKNOWNs, and gets richer as lanes fill the blocks. No lane is blocked on a contract change.
- Fabrication is structurally hard: the card cannot print a value that has no basis, and tests pin it.
