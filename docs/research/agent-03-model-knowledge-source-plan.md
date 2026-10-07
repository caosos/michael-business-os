# Source plan: non-recall model knowledge for the opportunity card (C-17 / P-03-07)

**Agent 03, with Agent 02 (sources), 2026-10-07.** Tags: **FACT** = verified on a primary page or in code; **INFERENCE**; **RECOMMENDATION**; **UNKNOWN**.

## 1. Where we are
- The `value_add` block (C-16) can name model-specific risks, but its knowledge base holds only **six CPSC recall entries**. Most listings therefore show "no sourced knowledge".
- That is honest, not good enough. Michael is an experienced mechanic; the useful content is the stuff he would otherwise carry in his head or dig out of forums: **known weak points, expensive parts, parts availability, unusual service intervals, resale demand for a specific model.**
- Searches for the Cub Cadet ZT1 and the Husqvarna FS 400 LV found nothing citable: only spam mirror sites and vendor marketing. (FACT, C-16 receipt.)

## 2. The admission standard (what may ever enter the KB)
An entry ships only if **all** of these hold. The code enforces the ones marked ✔.
1. ✔ It is about a **named make AND model** (a bare category is not knowledge).
2. ✔ It has a **named source with a URL and a date** (primary page, manufacturer document, agency record), **or** a **named human author with a human provenance record** (the `manual` path below). There is no third option.
3. ✔ It carries its **basis**: FACT only for what a primary page states; owner-stated knowledge is **RECOMMENDATION**; anything inferred is INFERENCE and says so.
4. ✔ It contains **no elementary advice** (the card lints it) and states what is **specific to the model**.
5. It is **economically material** to the buy decision: cost, safety or liability, parts availability, resale. Trivia stays out.
6. ✔ Applicability rests on the listing's own words and the card says so ("not verified against the unit"). Remedy and repair status that a source cannot settle are marked UNKNOWN.
7. **Never admissible:** text written or summarized by a language model with no underlying source; scraped content republished verbatim (copyright); anything from a source on Agent 02's do-not-automate list.

## 3. Candidate routes, ranked

| # | Route | Yields | Applies to | Access tier (ADR-02-0202) | What I verified | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Michael's own notes** (built in C-17) | weak points, expensive parts, part swaps, what a model is really worth | everything he knows | owned channel, no third party | FACT: the entry path exists and is tested | **Best source. Start here.** |
| 2 | **CPSC recalls API** (scale the recall entries) | recall defects, model numbers, units, remedies | every consumer product category in scope | Tier 1, official API | FACT (CPSC page, read 2026-10-07): endpoint `https://www.saferproducts.gov/RestWebServices/Recall`; query parameters `Title`, `RecallDescription`, `ProductName`; JSON via `&format=json`; page mentions no key; "machine readable access to publicly available recall information". UNKNOWN: the response field list (it is in a separate programmer's guide the page does not reproduce) and any rate limit | **Do next (recall coverage, not new knowledge types).** Needs the guide read first |
| 3 | **NHTSA** (road vehicles: `project_vehicle` only) | recalls by make/model/year; owner **complaints** by make/model/year (a real weak-point signal); service bulletins | project vehicles, not power equipment | Tier 1, official API and downloads | INFERENCE (a search-result summary of nhtsa.gov; the page itself blocked my fetcher with a 403): `api.nhtsa.gov/recalls/recallsByVehicle?make=&model=&modelYear=` and `api.nhtsa.gov/complaints/complaintsByVehicle?...`; bulletins appear only as **downloadable files** by year range (e.g. `TSBS_RECEIVED_2025-2026.zip`), not an API | Worth it for vehicles. Confirm endpoints on the live site before building |
| 4 | **Manufacturer manuals and parts diagrams** (public PDFs, OEM parts lookups) | service intervals, torque specs, part numbers, which parts exist | everything with a published manual | public documents; no scraping of a login or an internal endpoint | UNKNOWN: per-manufacturer terms and whether stable URLs exist | Use as **citations for Michael's notes** (reference URL), not as an automated feed |
| 5 | **Owner forums, Reddit, YouTube repair channels** | where real weak points are discussed | popular models | Tier 3 at best; Facebook groups and Nextdoor are **forbidden** | FACT: ADR-02-0202 forbids FB groups and Nextdoor automation. UNKNOWN: each other site's terms and robots rules | **Do not scrape.** Michael may paste a link and his own paraphrase as a `manual` note with `reference_url` |
| 6 | **Paid repair databases / dealer portals** | bulletins, repair times | vehicles, some equipment | licensed | UNKNOWN: cost and licence terms | Not now. Revisit if the volume justifies it |
| 7 | **Language-model summaries of the above** | fluent text | — | — | FACT: inadmissible under the standard in §2 | **Rejected.** Fluent and unsourced is exactly what the card must not show |

## 4. The manual path (built in this task)
- **Entry:** `python -m mbos_economics note new ...` or `valueadd.new_manual_note(...)`. It returns a validated **note** plus a **human provenance record** (`actor_type: human`, `human_actor`, tool `mbos.manual_note`). It writes nothing and reads no clock: the entry channel supplies `entered_at`.
- **Persist order:** the entry step records the provenance FIRST, then stores the note. A note's `provenance_id` must be that persisted record.
- **Required:** author, timestamp (with timezone), basis of knowledge ("own experience", "service manual p.34", "forum thread"), at least one make and one model, a `kind`, a statement of up to 600 characters. Optional: `plan_hint`, `reference_url` (https), `review_after`.
- **Refused at entry:** elementary advice (with a message saying what to write instead), a claim of FACT, a note with no model, malformed provenance, and non-https links. The loader reports every problem and returns nothing partial.
- **Shown on the card as:** basis **RECOMMENDATION** (owner-stated, never FACT), source "michael's own note (own experience), entered <date>", and the note's own provenance id. A sourced recall for the same model stays first.
- **Cannot ship by accident:** `load_kb` refuses any `origin: manual` entry in a KB file. Notes merge in memory via `merge_manual` from the operator's notes document, which lives outside the package.
- **Retraction:** `"retracted": true` removes a note from use while the record stays for audit.
- **The best prompt for Michael is the card itself.** When a card shows "no sourced knowledge for this model", it can offer "Add what you know about this model". The cost is thirty seconds of his time at the exact moment it is most valuable.

## 5. Who does what
| Piece | Owner |
|---|---|
| Admission standard, KB schema, manual-note validation, merge, tests | **03** (done in C-17) |
| Read the CPSC programmer's guide; a read-only, fixture-first CPSC knowledge adapter (Tier 1) emitting recall records with the record URL as source | **02** |
| A deterministic recall-record → KB-entry converter (template, no free text) and its tests; verify model-token extraction before anything auto-ships | **03** |
| NHTSA adapter (recalls and complaints by vehicle, bulletins from downloaded files) | **02**, after the CPSC adapter |
| "Add what you know" prompt on the card and the notes store (persist provenance first, then the note) | **06** (UI) and **01** (spine and state) |
| Policy: whether auto-converted recall entries ship without a human glance | **01** to rule, **05** to advise |

## 6. Open items (UNKNOWN)
- The CPSC response schema and rate limits (read the programmer's guide).
- Whether the CPSC `Model` text parses into discrete model tokens reliably enough for automatic conversion. If not, converted entries go to a review list and not straight to the KB.
- NHTSA endpoints and terms, to be confirmed on the live site.
- Where the operator's notes document lives at runtime (a store row or artifact is cleaner than a file). That is 01 and 04's call; the code takes a document or a path.
- Coverage targets. The right measure is the share of the listings Michael actually acts on that show at least one sourced risk. We have no real listing volume yet.
