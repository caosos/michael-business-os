# Receipt: G-05, Deal Sniffer card acceptance (Agent 07, lane G)

- **Task:** G-05 (P1, ADR-0011). **Claimed** `6be8c43`. **Delivered** `3c330e8`. DRY-RUN only.
- **Result (FACT):** 148 passed, 87 failed of 236 cases. Every failure is mapped to a finding; none are unmapped. Report: `docs/qa/CARD_ACCEPTANCE.md`. Findings F-26 … F-39: `docs/qa/ACCEPTANCE_REPORT.md`.
- **Under test:** `mbos.card` at Agent 01 `f8407c9` (installed from `git archive`, non-editable). Configurations:
  - pure (no database)
  - reference backend
  - lane D `92d52b1` + lane E `101a7e6`
- **Independence:** cards are validated with this lane's byte-pinned `qa/ext/card.schema.json` (format checks on) plus the honesty rules re-implemented from the ADR. They are not validated with 01's `validate_card`, which is itself under test.

## Held under attack
- NEGOTIATING and QUALIFIED are never invented (200 adversarial histories + 9 real flows).
- The trail equals the ledger 1:1 on 9 real flows, on both backends, and every row's provenance resolves.
- The card is read-only (no row changes in 8 tables).
- card_hash is stable across processes and PYTHONHASHSEED, independent of generation time, and equals an independent MBOS-CJSON-1 recomputation.
- No authority fields; the recommendation is unaffected by hostile text or by enrichment trying to override it.
- Atomic enrichment (D-16) and the F-23 fix hold.

## Defects (details and recommendations in the report)
| ID | Sev | One line |
|---|---|---|
| F-26 | high | `build_card` crashes on malformed enrichment (250/300 fuzz); one bad lane block hides the opportunity |
| F-31 | high | A dry-run is shown as "CONTACT SENT … waiting for the seller's reply" |
| F-35 | high | Newlines/ESC/CR/BEL in listing text forge card sections and hit the terminal; a 1 MB title → a 1 MB view |
| F-36 | high | A NUL in a listing aborts the whole discover batch (the root cause is hidden by a PicklingError) |
| F-30 | med-high | The elementary-advice lint misses 19 of 42 phrasings; junk "sources" launder; no model-specific marker |
| F-32 | med | Any outcome → CLOSED; Michael's YES never appears as CONTACT APPROVED; a reply is never SELLER RESPONDED |
| F-27, F-28, F-29, F-33, F-34 | med | invalid cards emitted; impossible values as FACT; unsourced `why`; order-dependent card_hash; hash not verified |
| F-37, F-38, F-39 | low | injection flag invisible; foreign receipts not filtered; the card's HOLD collides with Michael's HOLD |

## Corrections made while building the suite (before commit)
- My first lint tests used a `kind` value outside the contract's enum, so some tests passed for the wrong reason (the schema rejected them, not the lint). I fixed this by reading the actual errors and using real kinds.
- My control-character set wrongly included TAB. Fixed.
- The first backend run failed on the lane-D side because my pin predated D-16 (`append_item_research`). I re-pinned lane D to `92d52b1`.
- The reference-spine provenance helper needs a full document with an id; fixed.
- A finding in my own earlier work was re-checked and closed: F-16 (packaging) is verified fixed by A-10.

## Not covered
- The Operator UI rendering of the card (lane 06).
- Lane B/C enrichers, which only now run in the workflow; their blocks were exercised through the public `record_enrichment` seam.
- The `mbos card` CLI process itself (the same functions are called in-process).
