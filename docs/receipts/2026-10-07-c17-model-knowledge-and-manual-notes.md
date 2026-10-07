# Receipt: C-17, source plan for non-recall model knowledge + the `manual` notes path (Agent 03, with 02)

- **Date:** 2026-10-07
- **Task:** `C-17` (READY_QUEUE @ agent-01 `f8407c9`; P-03-07). Claimed at `14f6b15`. Code at `3569efb` (package 0.10.0).
- **Scope:** this branch only; read-only web research; nothing external contacted. Agent 02 did not need to change anything for this task: the source plan assigns it the adapter work.

## Deliverables
1. **`docs/research/agent-03-model-knowledge-source-plan.md`**
   - the admission standard
   - seven ranked routes, each marked with what was verified, what came from a search summary, and what is unknown
   - the division of work between 02, 03, 06, 01 and 05
2. **The `manual` entry path** in `valueadd.py`: `new_manual_note`, `load_manual_notes`, `merge_manual`, plus CLI `note new` / `note check`.

## The source plan's findings (honest status)
- **Michael's own notes are the best source** and are now buildable. The cost is thirty seconds at the moment the card says "no sourced knowledge".
- **CPSC recalls API** (FACT, read on the CPSC page 2026-10-07):
  - endpoint `https://www.saferproducts.gov/RestWebServices/Recall`
  - parameters `Title`, `RecallDescription`, `ProductName`
  - JSON via `&format=json`
  - the page mentions no key

  The **response field list and any rate limit are UNKNOWN**: they sit in a programmer's guide the page does not reproduce. This route scales *recall* coverage; it is not new knowledge types.
- **NHTSA** (road vehicles only): recalls and complaints by make/model/year, bulletins only as downloadable files. **INFERENCE**: this comes from a search-result summary because the NHTSA page returned HTTP 403 to my fetcher, so endpoints need confirming on the live site.
- **Forums and videos:** do not scrape (Agent 02's tiering forbids Facebook groups and Nextdoor, and the other sites' terms are UNKNOWN). Michael can paste a link plus his own paraphrase as a note.
- **Language-model summaries are inadmissible:** fluent and unsourced is exactly what the card must not show.

## How "nothing unsourced ships" is enforced (tested)
| Rule | Enforced by |
|---|---|
| A note needs an author, a timestamp with timezone, a basis of knowledge and a persisted human provenance id | `_note_problems`; the loader reports every problem and returns nothing partial |
| A note must name a make AND a model | validation (a bare category is refused) |
| A note is owner-stated: basis is always RECOMMENDATION | validation refuses `basis: FACT`; the card shows RECOMMENDATION |
| No elementary advice | refused at entry with guidance ("say what is specific to THIS model") |
| A manual note can never sit in the shipped KB | `load_kb` raises on any `origin: manual` entry, and a test scans the packaged file |
| Every shipped KB entry has an https primary source | enforced on load; tested against the packaged file |
| Sourced entries stay first and unmodified | `merge_manual` works on a copy (tested) |
| The note's own provenance reaches the card | the risk's `provenance_id` is the note's human provenance, and the run provenance lists it in `derived_from` |
| The entry channel, not the library, supplies time | no clock read (tested by scanning the source) |

## Bugs found and fixed during the work (FACT)
1. A naive timestamp raised a raw `ValueError` from the id derivation instead of a friendly `NoteError`, because ids were derived before validation. Fixed, and tested.
2. Validation stopped at the first missing field, so the documented "lists every problem" was untrue. Each check is now independent.
3. My own test fixture said "riding mower" while the comps said "zero turn". The vocabulary rule correctly rejected every comp, so the item was never scored. The fixture was corrected; the rule worked as designed.

## Evidence
- **25 new tests**: creation, a provenance record valid against Provenance v1, refusals, merge semantics, the nothing-ships guarantees, CLI exit codes, and the real `mbos.card.validate_card` with a manual risk.
  - The John Deere X380 is also in the Kawasaki engine recall, so the card shows the sourced FACT first and Michael's RECOMMENDATION second.
- **Suite:** 278 passed with all environments, 267 with 11 clean skips by default, and the py3.10 stdlib run is OK.

## Open (UNKNOWN)
- The CPSC response schema and rate limits.
- NHTSA endpoints and terms.
- Where the operator's notes document lives at runtime (a store row or artifact is cleaner than a file; 01 and 04's call).
- The UI prompt that asks Michael for a note is 06's.
- A real coverage measure needs real listing volume.
