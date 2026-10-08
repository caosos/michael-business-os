# Mission dry-run (G-21a): stages 1-4 on the real assembly

Date 2026-10-08. Agent 07 QA, fresh worker. DRY-RUN only: nothing was sent, bought, published or contacted; no other lane's branch touched.
Assembly: detached worktree of coordinator `63e24f8` (`/tmp/a07g21b/w`), `tools/bootstrap_dev.py --ui-pin g21pin` (lane pins: 04 `6bdf941`, 05 `44a0fb2`, 06 `073a71c`, 03 `1262a85`, 02 `55a7e19`), fixture `fixtures/sources/training_examples.json` (4 listings: TV, Recon, mower, drywall lead). Findings continue the series after F-101.

Verdict so far: see each stage. Written incrementally; one commit per stage.

## Setup

```
$ .venv/bin/python -I tools/bootstrap_dev.py --ui-pin g21pin
mbos-economics <- origin/research/agent-03-economics @ 1262a85: ok
mbos-governance <- origin/research/agent-05-governance @ 44a0fb2: ok
mbos-discovery <- origin/research/agent-02-opportunity @ 55a7e19: ok
freeze: released the initial global freeze as the owner (receipted, dev only) -> system RUNNING
bankroll: funded the dry-run bankroll $500 as the owner (receipted, dev only)
lane D 6bdf941 provisioned (mbos_dev); lane E policy 44a0fb2; lane F 073a71c; migrations applied this run: 25
```

(A-40 effects visible: freeze released and bankroll funded by bootstrap, F-89/F-96 style gaps from G-20 no longer need a manual step.)

## Stage 1: discovery: PASS

Command (worker shell, long-running):
```
$ source var/dev.env && .venv/bin/mbos worker --fixture fixtures/sources/training_examples.json
```
Result after 45 s: the worker stays up (pid alive), and four items exist.
```
$ .venv/bin/mbos items
itm_01M4EK0246KT4QGPG5RK46GRQK  RESEARCHING  service/drywall_repair       Patch two drywall holes and a ceiling stain
itm_01M4EK01ZQDJ2CN4V3B2KMY3MQ  RESEARCHING  flip/mechanical_equipment    Honda Recon ATV, doesn't run, $300
itm_01M4EK01VFDZ4JK3QPCX6SSYF6  RESEARCHING  flip/mower                   Older riding mower 42in, runs, needs a belt, $480
itm_01M4EK01Q9NPYPMQA69CC0EWJG  RESEARCHING  flip/other_asset             55 inch LED TV, works great, $30 firm, today only
```
Each of the 4 fixture listings (TRAIN-TV-1, TRAIN-RECON-1, TRAIN-MOWER-1, TRAIN-LEAD-DRYWALL-1) was fetched once: 4 listings in, 4 items out, none dropped, none duplicated.
Each item carries `sources[0]` with `source`, `source_listing_id`, `ingestion_method` (TV `manual`, mower/Recon `rss`, lead `inbound_form`), `tos_risk`, `raw_ref sha256:...` and a `provenance_id`.
Chain after discovery: `mbos audit` -> `chain.ok true (59 receipts)`, `provenance.ok true`, `dry_run.ok true (effector_receipts 0)`.

Notes (not failures of this stage):
- `mbos worker` prints nothing to its log for its first 45 s (no REAL/STAND-IN report appeared in `worker.log`, 0 bytes); the RUNBOOK says it prints one. INFER: stdout buffering of a redirected `nohup` run. Recorded as F-103 (P3).
- `ls var/raw` is empty, so the `raw_ref sha256:` values cannot be resolved to a stored raw document on disk (`MBOS_RAW_DIR=var/raw`). Recorded as F-104 (P2, INFER: the raw store may be database-side).

## Stage 2: normalization: PASS on the acceptance (4/4 Items) with two contract-conformance findings (F-102, F-105)

Commands:
```
$ .venv/bin/mbos items | wc -l                                  # 4
$ psql-equivalent read of mbos.items (item_id, sources[0].source_listing_id, source, ingestion_method, dedup_key):
itm_01M4EK01Q9NPYPMQA69CC0EWJG  TRAIN-TV-1             facebook_marketplace_manual  manual        other_asset|tv|conway|train-tv-1
itm_01M4EK01ZQDJ2CN4V3B2KMY3MQ  TRAIN-RECON-1          craigslist                   rss           mechanical_equipment|recon|conway|train-recon-1
itm_01M4EK01VFDZ4JK3QPCX6SSYF6  TRAIN-MOWER-1          craigslist                   rss           mower|riding|conway|train-mower-1
itm_01M4EK0246KT4QGPG5RK46GRQK  TRAIN-LEAD-DRYWALL-1   website_lead                 inbound_form  drywall_repair|lead|conway|train-lead-drywall-1
```
Every training deal is an Item with `type`, `category`, `subcategory`, `opportunity_kind`, `dedup_key`, `content_hash`, `normalized` (title, condition, price object, location with `geo_tier`, counterparty, listing_status, flags), `economics`, `provenance_ids`. The TV keeps its `underpriced` flag, which the card surfaces ("listing text needs Michael's eyes").
Dedup keys are unique, stable and name the listing id. Four listings, four distinct keys, no merge.

Contract conformance of the normalized Items (the system's own check):
```
$ .venv/bin/mbos audit        # exit 1
chain.ok true (59 receipts) | provenance.ok true | dry_run.ok true (0 effector receipts)
conformance.ok FALSE:
  item itm_01M4EK01Q9N...: economics: Additional properties are not allowed ('context' was unexpected)   (x4, one per item)
  item itm_01M4EK01ZQD...: economics/estimates_meta/assumptions/1/basis: 'UNKNOWN' is not one of ['FACT', 'INFER', 'REC', 'UNK']
```
- **F-102 (P1, FACT; owner 01 + 03):** every Item stored by the real assembly has `economics.context = {"available_to_deploy": 500.0}` (read from the ledger by the researcher/scorer, `production.py:59/88` `context_source=ledger`). The frozen `item.schema.json` forbids extra keys under `economics`, so `mbos audit` exits 1 on a healthy fresh install (4 of 4 items). Repro: bootstrap, `mbos worker --fixture fixtures/sources/training_examples.json`, `mbos audit`. Recommendation: keep the capital context outside the stored Item (derive it at scoring time) or add it to the contract by ADR; add a post-worker `mbos audit == 0` check to `test_a41_training_examples.py`.
- **F-105 (P2, FACT; owner 01 fixture A-41 + 02 normalizer):** `training_examples.json` writes `estimates_meta.assumptions[].basis = "UNKNOWN"` (lines 106, 133); the contract vocabulary is `FACT|INFER|REC|UNK`. Lane B passes it through unvalidated and it lands in the Item (Recon). Recommendation: fix the fixture (`UNK`) and have the normalizer reject or map unknown bases.
- **F-103 (P3, FACT; owner 01):** `mbos worker` log stays at 0 bytes (the RUNBOOK promises a REAL/STAND-IN report), also after 3 minutes. See Stage 1.
- **F-104 (P2, INFER; owner 02/01):** `var/raw/` is empty although items carry `raw_ref sha256:`; raw payloads cannot be re-read from disk for audit.

I do not treat F-102/F-105 as blocking Stage 3: the Items exist, are RESEARCHING with provenance and a valid receipt chain, and later stages can run. They are filed as gaps and the audit stays red until fixed.

## Stage 3: research ("Add a price I saw" through the UI): FAIL (the TV cannot leave research; F-106, F-107, F-108)

Setup: Operator UI started exactly as bootstrap printed it (`source var/dev.env && source var/owner.env && MBOS_OPERATOR_PIN=g21pin .venv/bin/python -u -m operator_ui serve --port 8765`; `MBOS_OWNER_DATABASE_URL` is read, F-88 fixed). Driven over HTTP the way the browser posts (CSRF + nonce + PIN). Home `/` lists "Needs from you (4)": TV, mower and Recon "no comparable sold price"; the lead "more evidence".

What worked:
- Bad PIN on `/item/<tv>/comp` is refused and writes nothing; right PIN writes `var/comps_inbox/ui-*.json` with `entered_by michael`, `entered_via operator_ui`, a provenance note. The banner is now true: "The worker checks the inbox about once a minute and will re-check this item with your price" (F-92 FIXED).
- The running `mbos worker` picked the file up by itself within ~45 s and re-checked all four items (`recheck:<item>:<epoch>` DBOS workflows, all SUCCESS). No `mbos recheck` needed (F-91 not hit: a second `mbos recheck` for the TV also SUCCEEDED).
- After comps for the mower ($700) and Recon ($1,050), both moved from "no comparable sold price" to scored cards (see Stage 4).

What failed, in order met:
1. **F-106 (P0, FACT; owner 03 + 01 + 06): the TV, the primary training deal, cannot reach a recommendation in the bootstrapped assembly.** With its comp in place, lane C's research step still returns `RESEARCHING` with a blocking gap `scope_override_required`: "flip/other_asset is uncategorized: a human must supply rehab.parts_cost, rehab.labor_hours, rehab.required_skills as provenance-carrying overrides". The Operator UI has no form for this (only "Add a price I saw", "My notes" and the lead's attest keys), and `training_examples.json` already carries exactly these values inline (`rehab.parts_cost 0, labor_hours 0.2, required_skills [assembly]`). Repro: bootstrap, worker with the fixture, add a TV comp titled "55 inch LED TV" (the research call in a Python shell: `research_step(item, comps, prov, as_of)` -> `proposed_next_state RESEARCHING`, gaps `[scope_override_required, blocking]`). **INFER (cause of the A-41 divergence):** A-41's `training_set` runner sets no `MBOS_COMPS_STORE`/`MBOS_COMPS_INBOX`, so research is a STAND-IN and the inline economics are scored as given (TV = YES); `bootstrap_dev`'s `var/dev.env` sets both, so the REAL researcher re-estimates every listing from category priors and overrides the fixture's FACT values. The documented path (bootstrap + `mbos worker` + UI) therefore does not reproduce A-41. Recommendation: (a) the researcher must honour inline FACT/attested economics (or accept a human scope override from the UI); (b) add an A-41-style test through `bootstrap_dev`'s env, not a stripped env.
2. **F-107 (P1, FACT; owner 03 + 06):** the status text lies for the TV. After a matching comp is on file the UI still says "Needs from you: no comparable sold price ... This item is parked: the system cannot recommend it until it has a price to compare with"; the true blocker is `scope_override_required`. The card says "more research is running" (nothing is). This is F-93 again for a new gap code; the card's `UNKNOWN (36)` list does not name it either.
3. **F-108 (P1, FACT; owner 02 + 06):** a saved comp can be silently ignored. The first TV comp I typed with the form's natural fields ("Generic" / "55in LED TV", $92, used) was saved, the banner said it would be re-checked, the worker re-checked, and nothing changed: lane B's `candidate_comps` drops comps whose title similarity to the listing title is below 0.5 (`title_similarity("55 inch LED TV, works great, $30 firm, today only", "Generic 55in LED TV") = 0.453`; "Generic 55 inch LED TV" = 0.50, "55 inch LED TV" = 0.58). The UI never tells Michael a price was not used. Second comp ("55 inch" / "LED TV") matched. Recommendation: the form should say which listing it is attached to and use its title when make/model is blank; report "price saved but not matched to this listing (similarity 0.45 < 0.5)".

Evidence of state after stage 3 (dev DB; the TV is the blocker):
```
$ .venv/bin/mbos items
itm_01M4EK0246KT4QGPG5RK46GRQK  RESEARCHING  service/drywall_repair       Patch two drywall holes and a ceiling stain
itm_01M4EK01ZQDJ2CN4V3B2KMY3MQ  RESEARCHING  flip/mechanical_equipment    Honda Recon ATV, doesn't run, $300
itm_01M4EK01VFDZ4JK3QPCX6SSYF6  RESEARCHING  flip/mower                   Older riding mower 42in, runs, needs a belt, $480
itm_01M4EK01Q9NPYPMQA69CC0EWJG  RESEARCHING  flip/other_asset             55 inch LED TV, works great, $30 firm, today only
$ .venv/bin/mbos queue
Nothing needs a decision.
research_step per item (read-only call, current comps): TV RESEARCHING [scope_override_required, blocking] (1 comp);
  mower SCORED [thin_comps "1 sold comps; YES needs 3", repair_scope_unknown]; Recon SCORED [thin_comps, repair_scope_unknown, transport_unclassified];
  lead SCORED [scope_unverified]
```
Per the task I stop at the first real gap. Stage 4 below records what the same state shows, so the owner can see the whole distance in one pass.

## Stage 4: scoring + recommendation: FAIL (1 of 4 expected outcomes met; same root cause as F-106)

Expected (task / A-41) versus observed on the bootstrapped assembly after the Stage 3 comps and the UI attestations:

| Deal | Expected | Observed (`mbos items`, `mbos show`, `mbos card`) | Result |
|---|---|---|---|
| 55in TV, $30 | YES, approvable within $500 | `RESEARCHING`, HOLD, no score: blocked on `scope_override_required` (F-106); `mbos queue` -> "Nothing needs a decision." | FAIL |
| Honda Recon, $300 | MAYBE naming its evidence (`fault_identified`) | verdict `PASS`, state `RESEARCHING`: "Passed because cash tied up of $538 is over your $500 per-deal limit ... held for research"; `cheapest_decisive_evidence` None; repair prior $210 replaces the fixture's $100 + $80 (F-110) | FAIL |
| Riding mower, $480 | PASS on the bankroll | verdict `PASS` ("cash tied up of $572 is over your $500 per-deal limit"), but state `RESEARCHING`, not ARCHIVED: "R13: PASS is not evidence-backed (cash_ok: no decisive input backed ...): route to RESEARCHING". The fixture's buy price is FACT; the researcher did not carry it (F-110) | PARTIAL (right reason, wrong state) |
| Drywall lead | MAYBE, then YES after Michael confirms evidence in the UI | MAYBE ("Needs from you: more evidence"); the UI now has seven "Confirm what you know" forms (F-90 fixed); `scope_verified` and `customer_screened` accepted ("Confirmed ... Your word is recorded (human, receipted)"); after `mbos recheck` the card reads "Not a YES yet: about $73/h expected, under your $75/h service target. Quoting $651 or more would clear it. YES blocked: composite 58.20 < 60; EV profit/hour $72.99 < $75.00". Confidence is no longer the blocker (it was 0.15 < 0.60). Still MAYBE | FAIL (but the attestation path works; the economics now decide) |

Commands: `.venv/bin/mbos items`, `.venv/bin/mbos queue`, `.venv/bin/mbos card <id>`, `.venv/bin/mbos show <id>`, UI `POST /item/<lead>/attest` (key `scope_verified`, then `customer_screened`, PIN `g21pin`), `.venv/bin/mbos recheck <lead>`.

Findings:
- **F-109 (P2, FACT; owner 01 + 06):** a UI attestation does not wake the worker. The comps inbox is watched (60 s) but attestations are not; the lead stayed RESEARCHING after both "Confirmed" banners until I ran `mbos recheck` by hand (the banner tells Michael to do so on the server). Recommendation: have the attest route (or the worker) trigger a recheck of that item.
- **F-110 (P1, FACT/INFER; owner 03; root cause shared with F-106):** with a REAL researcher the stored inline economics (`acquisition.expected_buy_price` FACT, `rehab.parts_cost` etc.) are replaced by category priors, so the mower PASS is "not evidence-backed" and the Recon becomes a PASS instead of a MAYBE naming `fault_identified`. The fixture documents these as FACT/INFER/UNK with `estimates_meta.assumptions`; the researcher should read them. A-41's green test hides this because it runs without comps wired.

Gaps are not the system's design intent: the cards are honest and every number is labelled; what fails is that the documented production path cannot reproduce Michael's three training examples.

## Verdict (G-21a)

| Stage | Result |
|---|---|
| 1 discovery | PASS (4 of 4 listings fetched) |
| 2 normalization | PASS on acceptance (4 of 4 Items); `mbos audit` conformance red: F-102, F-105 |
| 3 research (UI comp, worker pickup) | FAIL: UI + worker mechanics work; TV blocked by F-106; F-107, F-108 |
| 4 scoring + recommendation | FAIL: TV not YES, Recon not MAYBE, mower PASS not archived, lead still MAYBE (F-110) |

Chain, provenance and dry-run held throughout: `mbos audit` -> chain ok (receipts verified), provenance ok, `dry_run.ok true`, `effector_receipts 0`. Nothing was sent, contacted, bought or published.

Findings filed (after F-101): F-102 (P1), F-103 (P3), F-104 (P2), F-105 (P2), F-106 (P0), F-107 (P1), F-108 (P1), F-109 (P2), F-110 (P1).
G-21b (stages 5-8) is BLOCKED on F-106/F-110: there is no YES to approve on this assembly.

---

# G-21c: re-run of stages 3-4 on the FIXED assembly

Date 2026-10-08. Agent 07 QA, fresh worker. DRY-RUN only. Assembly: detached worktree of coordinator `6ddbfb4` (A-42 `69402d9`, C-26 `3d0fd86`, B-22 `3b77cd0`, F-31 partial `cd174fa`), fresh venv, `tools/bootstrap_dev.py --ui-pin g21pin` (lane pins: 03 `3fb7502`, 05 `44a0fb2`, 02 `a2b971d`, 04 `6bdf941`, 06 `96fb674`), fixture `fixtures/sources/training_examples.json`. Worker and Operator UI started exactly as bootstrap printed them (UI on port 8791; 8765 was taken by an unrelated websocket server). The UI is driven over HTTP the way a browser posts (CSRF + nonce + PIN). Worker report: everything REAL except `sources`.

Fresh start: 4 listings -> 4 Items, `chain.ok true` (80 receipts) after the comp below.

## Stage 3 (G-21c): research via "Add a price I saw": PASS

Repro of the exact G-21a failure: on the TV item's form I typed the natural fields that were silently ignored before (F-108): make `Generic`, model `55in LED TV`, $92, used, sold 2026-10-01, PIN `g21pin`.

- UI banner: "Price saved. The worker checks the inbox about once a minute and will re-check this item with your price" (the file `var/comps_inbox/ui-*.json` was written).
- The running worker queued `recheck:<item>:<epoch>` for all four items by itself (no `mbos recheck`). Within ~75 s of the save the TV moved `RESEARCHING` -> `AWAITING_APPROVAL`. F-108 FIXED: the comp is paired to the TV (`for_item_id`) and used despite a title similarity of 0.45.
- F-106 FIXED in the path that matters: no `scope_override_required` for the TV; `flip/other_asset` is estimated from C-26 priors (no override form needed).
- F-110 (listing facts) seen fixed for the TV: card shows `asking $30 FACT provenance`.

```
$ .venv/bin/mbos items
itm_01M4ENBSGMQKXGMD4HXTCMAWS0  AWAITING_APPROVAL  flip/other_asset  55 inch LED TV, works great, $30 firm, today only
$ .venv/bin/mbos queue
[PENDING_APPROVAL] 55 inch LED TV ... verdict YES composite 64.27 EV $53.21 $86.28/h confidence 0.95
  deterministic: net $55.51, $90.01/h over 0.6167 h, cash tied up $36.49 ; walk-away price (max buy for YES): $35
  action comms.email.send (tier 0, irreversible): Ask the seller ... (first contact, no offer)   areq_01M4ENFGT9Q7EG5Y6BVRRWPHSV
```
UI home ("Today"): "Best next move: Decide: 55 inch LED TV ... is ready for your YES or NO", "Needs your decision (1)", "EV $53 $86/h confidence 0.95 irreversible". Cash tied up $36.49 is within the $500 bankroll.

## Stage 4 (G-21c): scoring + recommendation: PARTIAL (3 of 4 expected outcomes met; the lead never reaches YES: F-111)

Comps for the mower ($700) and the Recon ($1,050) were entered through the same UI form; attestations through the UI "Confirm what you know" forms (PIN `g21pin`). No `mbos recheck` was ever run: the worker log shows `comps inbox changed: queued recheck:...` and `new evidence on a parked item: queued recheck:<lead>:...` (about 60 s after each attestation).

| Deal | Expected | Observed | Result |
|---|---|---|---|
| 55in TV, $30 | YES within $500, in `mbos queue`/Today | `AWAITING_APPROVAL`, YES, composite 64.27, EV $53.21, $86.28/h, confidence 0.95, cash tied up $36.49; in `mbos queue` and the UI "Needs your decision (1)" / "Best next move" | PASS |
| Honda Recon, $300 | MAYBE naming its evidence | `recommendation.verdict MAYBE`, state `RESEARCHING`; "YES blocked: repair fault not identified (guessed scope caps at MAYBE)", "confidence 0.42 < 0.60 (gather evidence)", "Economically it works up to $277"; UI offers `fault_identified` among five forms. After I attested `fault_identified`: confidence 0.42 -> 0.57, composite 48.03 -> 49.36, still MAYBE (evidence helps but is not enough alone). F-110 fixed for the listing's own facts | PASS |
| Riding mower, $480 | PASS, archived | `ARCHIVED`; "Passed because cash tied up of $699 is over your $500 per-deal limit ... " and `R13: PASS is evidence-backed (ev_positive, cash_ok, pph_floor_ok, class_profit_ok)` | PASS |
| Drywall lead | MAYBE, then YES after attestations, worker rechecks by itself | MAYBE at first (confidence 0.15 < 0.60); worker rechecked on its own after each attestation (F-109 FIXED); after `scope_verified` + `customer_screened` confidence stops blocking, still MAYBE: composite 58.20 < 60 and EV $72.99/h < $75/h service target ("Quoting $651 or more would clear it"). After all six attestations the UI offers (adding `materials_priced`, `repeat_or_referral`, `price_agreed_in_writing`, `access_and_schedule_confirmed`) only the $/h gate remains: "Quoting $625 or more would clear it". Never YES | FAIL |

New finding:
- **F-111 (P1, FACT/INFER; owner 03, with 02/01 for the lead's own numbers): the drywall training lead cannot reach YES through the UI.** FACT: with every attestation the UI offers, the card stays MAYBE on `EV profit/hour $72.99 < service target $75.00`, and says a quote of $625+ would clear it, but there is no UI field for Michael to enter or accept a quote (the listing is `quote_requested`). The fixture's own economics (`quoted_revenue 450`, `labor_hours 3`, `admin_hours 0.5`, `materials_cost 40`) are the training example's YES case. INFER: the researcher re-estimates the job (6.43 h expected, net $551 deterministic) rather than using the lead's stated hours, same family as F-110 for service jobs. Repro: this document's setup, attest all seven keys on the lead, `mbos card <lead>`. Recommendation: the researcher honours stated job hours/revenue as FACT/INFER, and/or add a "My quote" input to the lead's page so the YES case is reachable; add a `bootstrap_dev` end-to-end test that asserts lead MAYBE -> YES.

Observation (not filed): the Recon and lead cards print "evidence is not the blocker: no missing evidence item changes the verdict" next to "YES blocked: confidence ... (gather evidence)"; the verdict indeed stays MAYBE but the sentence reads as contradictory to Michael. Candidate F-112 (P3, owner 03/06: reword to "more evidence raises confidence but the verdict stays MAYBE because ...").

Audit after all stages: `mbos audit` -> `chain.ok true (136 receipts)`, `provenance.ok true`, `dry_run.ok true (effector_receipts 0)`, **`conformance.ok true`** (F-102 fixed).

## Verdict (G-21c)

| Stage | G-21a | G-21c |
|---|---|---|
| 3 research (UI comp, worker pickup) | FAIL (F-106, F-107, F-108) | **PASS**: TV comp via the form is used, TV reaches YES with no override; worker rechecks by itself |
| 4 scoring + recommendation | FAIL (1/4) | **PARTIAL (3/4)**: TV YES, Recon MAYBE, mower PASS archived; lead stays MAYBE (F-111) |

Fixed since G-21a, re-verified: F-102, F-103 (report printed at start), F-104 (`var/raw` populated, card activity "from retained raw payloads"), F-106 (TV), F-108, F-109, F-110 (TV, mower, Recon). Not exercised: F-107's UI wording for `scope_override_required` (no such item now). Still seen: for the Recon, the page status line still says "parked ... until it has a price to compare with" although a comp is on file (UI text keyed off the state, F-107-like; part of F-112 candidate scope).
G-21b (stages 5-8) is unblocked: there is a YES to approve (areq_01M4ENFGT9Q7EG5Y6BVRRWPHSV on a throwaway cluster; re-bootstrap per G-21b).
