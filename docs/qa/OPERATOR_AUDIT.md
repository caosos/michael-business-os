# Operator audit as Michael (G-20)

Date 2026-10-08. Fresh worker, DRY-RUN only (nothing was sent, bought or published). Coordinator head `edda153` (A-39 merged, F-28 on 06 `3a30680`). Lane D `4a11f1b`, lane E policy `44a0fb2`, lane 03 `44e1beb`, lane 02 `55a7e19`.
Method: a detached worktree of the coordinator head, `tools/bootstrap_dev.py --ui-pin audit-pin`, `mbos worker --fixture fixtures/sources/illustrative.json` (long-running), Operator UI started as the RUNBOOK says, then every action done over HTTP exactly as the browser forms post (CSRF + nonce + PIN, redirects followed by hand). Pages below are HTML rendered to text (screenshots-as-text), trimmed. FACT = observed; INFER = reasoned.

## Verdict (G-20, superseded by the G-22 re-audit at the end of this file): can Michael use this today? NO

He can read a lot, and the money-numbers, Wanted and comp forms work **once the UI is started with a workaround** (F-88). But on the real assembly **no item can reach a decision**: all four fixture listings park, the two promising ones ask for evidence there is no way to enter (F-90), so "approve / decline / hold" (job 6) cannot even be attempted, and every re-check needs a terminal (F-92) and breaks on the second try (F-91). Two of seven jobs fail (2, 6), four pass only partially (1, 3, 5, 7), one passes (4, after the F-88 workaround).

| # | Job | Result | One-line reason |
|---|---|---|---|
| 1 | See what matters today | **PARTIAL** | `/` lists "Needs from you (4)" but not the weekly gap, bankroll or best opportunity; those are on `/mission` and `/digest` (F-98, F-95) |
| 2 | Understand the best money opportunity | **FAIL** | `/mission` says "DEPLOY capital to the legs below" for two unnamed legs that cannot be decided; three different dollar figures for the same job (F-94, F-95) |
| 3 | Create / update / pause a Wanted campaign | **PARTIAL** | create, pause, resume, cancel work and are receipted; no way to update; must-have / nice-to-have vanish after saving; nothing is hunting (F-97) |
| 4 | See bankroll / cash and set his numbers | **PASS with a P0 wiring bug** | works only when the UI is started with `MBOS_APPROVER_DATABASE_URL` (F-88); cards then still say "Cash situation UNKNOWN" (F-96) |
| 5 | Understand WHY a deal is worth pursuing | **PARTIAL** | the card's WHY is good for the trailer (gate failures, max price $243); contradictory on transport; service WHY asks for a sold price (F-99, F-90) |
| 6 | Approve / decline / hold one | **FAIL (not reachable)** | `Needs your decision (0)` in every state I could reach; `/api/queue.json` is `{"pending": [], "held": [], "closed": []}` (F-90) |
| 7 | Know what needs his decision vs input | **PARTIAL** | the two-list split is the right idea and reads well; but "Needs from you" items cannot be satisfied from the UI for 3 of 4 (F-90, F-92, F-93) |

## Findings, ranked (F-88 onwards; last filed was F-87)

| ID | Sev | Owner | Tag | Finding | Repro | Recommendation |
|---|---|---|---|---|---|---|
| F-88 | **P0** | 01 (bootstrap) + 06 | FACT | The Operator UI command that `bootstrap_dev` prints sources `var/owner.env`, which exports `MBOS_OWNER_DATABASE_URL`. The UI reads `MBOS_APPROVER_DATABASE_URL` (`operator_ui/__main__.py:ui_engine`), so it silently falls back to the worker login `mbos_dbos`. Every owner-channel write is refused: "Not saved. the store refused it: permission denied for function set_mission" (My numbers), "...permission denied for function capital_fund" (Fund $500). I did not exercise Wanted / decide on the broken UI; by the same grants they should fail too (INFER). | `source var/dev.env && source var/owner.env && MBOS_OPERATOR_PIN=audit-pin .venv/bin/python -u -m operator_ui serve --port 8765`; open `/numbers`, Save. Workaround: add `MBOS_APPROVER_DATABASE_URL="$MBOS_OWNER_DATABASE_URL"` -> Save works (receipt written). | UI should read `MBOS_OWNER_DATABASE_URL` (and refuse to start on the worker login, naming the variable). Add a bootstrap test that starts the UI and POSTs `/numbers/mission`. |
| F-89 | **P1** | 01 / 04 | FACT (banner, DB); INFER (effect on YES) | A fresh dev DB is born FROZEN: `mbos.panic_read()` returns `FROZEN`, every page header says "system FROZEN" with no explanation, and neither RUNBOOK nor bootstrap output mentions it. The gateway fails closed, so a YES would end FAILED / `cancelled_by_freeze`. I cleared it with `mbos panic off --reason ...` (owner env), after which the banner read RUNNING. | Run bootstrap, open `/`. | Bootstrap prints "the system starts FROZEN; release with `mbos panic off --reason ...`", or seeds RUNNING for dev. The banner should say what FROZEN means and the command to clear it. |
| F-90 | **P0** | 01 / 03 / 06 | FACT | No listing can reach a recommendation Michael can act on in the real assembly. All 4 fixtures stayed RESEARCHING / HOLD even with a comp, $500 funded and the target set. Doorbell (the best job: net $373, $53 at risk, 4 days) is blocked on "customer_screened + scope_verified -> YES" and drywall on "more evidence"; nothing in the UI or CLI can supply those (`grep customer_screened` finds nothing in src or UI; `mbos --help` has no such command). The UI instead shows the doorbell the form "Add a price I saw" with the text "the system cannot recommend it until it has a price to compare with", which is wrong for a service job. Drywall shows no form at all. | Open `/item/itm_..S738BKTD9GR7BZBJ79` (doorbell) and `/item/itm_..PTJCHQ2C1XY9P8PCBT` (drywall). | Add a "Customer screened / scope verified" confirmation (receipted, human channel) on service cards, and show it instead of the sold-price form for `lane=service`. Without it the product cannot produce a decision. |
| F-91 | **P1** | 01 | FACT | A second `mbos recheck` of an already-enriched item crashes the workflow: `UniqueViolation provenance_pkey` from `record_lane_provenance` via `EconomicsResearcher.enrich` (10 tracebacks in the worker log; DBOS logs them, the UI shows nothing). Consequence: a comp added after the first recheck never takes effect. Mower: comp saved, `mbos recheck --researching`, still "no comparable sold price... more research is running". | Add comp, `mbos recheck --researching`, wait, add another comp, `mbos recheck --researching`; read the worker output. | Make enrich idempotent (deterministic provenance ids must be upserted or skipped), and record the recheck failure on the item so the UI can say it. |
| F-92 | **P1** | 06 + 01 | FACT | Saving a comp is a dead end for a non-terminal user: banner "Price saved. The item has not moved yet: this page cannot re-check it. Run `mbos recheck ITEM` on the server". The worker is running yet does not watch the inbox. The card keeps showing "Needs from you" and the same empty form; there is no "your price is waiting to be re-checked" state. | `/item/<trailer>` -> Save this price -> read message -> reload. | Worker should poll the comps inbox (or the UI should enqueue the recheck through its own channel); until then, show "1 price waiting; run: ..." on the card and Today. |
| F-93 | **P2** | 03 | FACT | Wrong status text: "Not enough information yet to recommend an action; more research is running." appears when nothing is running (mower after the crash in F-91; and also first pass). | `mbos card <mower>` or the mower card. | Say what is true: "waiting for a price you saw" / "last re-check failed". |
| F-94 | **P1** | 01 mission / 06 | FACT | `/mission` headline: "DEPLOY capital to the legs below. Each still needs your own YES." The two legs are both MAYBE with evidence outstanding, so no YES can be given; legs are listed as class + numbers ("SERVICE_JOB $53 at risk") without the name of the job; "Replace if stale" shows raw ids (`itm_01M4E42QPTJCHQ2C1XY9P8PCBT`). | Set target + fund, open `/mission`. | Headline should depend on whether any leg is decidable ("Nothing is ready to approve; 2 jobs need your input"). Show titles, link the card. |
| F-95 | **P2** | 01 digest / 06 | FACT | Same doorbell, three figures: net $373 (card, `/mission`), "EV $246.50" (`/digest`), "Value 11.98" under "Value $/h" (`/digest`) and "$12" under Value (`/summary`). "Value $/h" holds a rank score, not dollars per hour (the same line says EV $79.84/h). | Compare `/item/..`, `/mission`, `/digest`, `/summary`. | One name per number; label the rank "priority score"; show net, per hour, cash at risk consistently. |
| F-96 | **P2** | 01 / 03 | FACT / INFER | After Michael types "about 500 free" and funds $500, `/mission` still lists `current_cash_context` as UNKNOWN and every card still reads "Cash situation: UNKNOWN". The $500 gate cap on the trailer card comes from somewhere else (INFER: `operator_profile.v1.json`, not his ledger), so two sources of "my cash" disagree silently. | `/numbers` -> save -> `/mission` -> `mbos card <trailer>`. | Feed the ledger's available-to-deploy and the cash text into `current_cash_context`; re-score on change. |
| F-97 | **P2** | 06 / 04 | FACT / INFER | Wanted: create (`5x8 utility trailer`, RECOMMEND), pause, resume work with receipts and strict validation (rejects `-5`, `nan`, ASSISTED_DEAL). Gaps: no way to edit a campaign (job 3 asks for "update"; only Pause/Resume/Cancel); Must have = "title" and Nice to have = "lights" are not shown after saving; the page says "4 current Items checked" while no source is hunting for it (INFER: campaigns only filter items already in the DB). | `/wanted` -> create -> pause. | Add edit (new revision); echo every field; say what is searching. |
| F-98 | **P2** | 06 | FACT | Home (`/`) answers "what needs me" but not "what matters today": no weekly target/gap, no bankroll, no top opportunity. They sit on `/mission` and `/digest`; the nav has 14 tabs. | Open `/`. | Put a three-line header on `/` (gap, available, best next move). |
| F-99 | **P2** | 03 / 06 | FACT | Trailer card (after the $1,850 comp): WHY lists "Fits the truck; no trailer needed" and "Towed behind the truck; its tow rating and hitch are not on file" while TRANSPORT says UNKNOWN; resale conservative/optimistic show UNKNOWN (they were $1,800/$2,400 before the comp); Today says only "Needs from you: evidence, not archived", while the true story ("$1,112 at risk vs your $500; the most you should pay is $243; offer $240") is the useful sentence and sits in the middle of the card. | `/item/<trailer>` after recheck. | Lead with that sentence; one transport statement; keep source values the comp does not replace. |
| F-100 | **P2** | 06 / 01 | FACT | Pages that depend on unset variables say UNKNOWN in the real assembly: `/sources` (MBOS_SOURCE_HEALTH_FILE), `/usage` (MBOS_READY_QUEUE_FILE, no telemetry), `/preview` (MBOS_INVENTORY_FILE). `dev.env` sets none of them. | Open the three pages. | Set sane dev defaults or hide the tab when unconfigured. |
| F-101 | **P3** | 01 | FACT | `bootstrap_dev` fails with `FileNotFoundError: <repo>/.tools/uv` in any checkout that did not run RUNBOOK section 2 step 2 (I copied uv in). `mbos worker` is silent and logs tracebacks to stdout only; the UI CSRF token is per-process, so a restart invalidates every open tab (it answers 200 with an error, not a redirect). | Run bootstrap in a fresh worktree. | Document or auto-fetch uv; tell Michael where the worker log is. |

**$1,500 / $3,000 / stale values:** none found on any page. The only $1,500 on screen is the target I typed. The only related literals are the "Confirm if over $2,000" and "limited to $5,000" fund limits and a 3,000-mile radius cap in the Wanted validator, none stale. Estimated values that do look stale: F-99 (resale range changes meaning after a comp) and F-96 (Cash UNKNOWN after he set it).

## What worked (PASS items)
- Manual comp form: bad PIN refused, good PIN wrote `var/comps_inbox/ui-*.json` with `entered_by: michael`, `entered_via: operator_ui` and a provenance note; the trailer then scored (PASS-on-gates, HOLD for evidence: "Economically it works up to $243").
- My numbers: target $1,500, hours 30, cash text, Fund $500 -> "Protected principal $500, Available to deploy $500"; `/mission` then showed gap $860 and "Probability this plan reaches $1,500 inside 7 days: 0.0000" (honest).
- Wanted validation and receipts; `/ledger` shows "chain verified (83 receipts)" and the independent check agrees.
- Every figure that is unknown says UNKNOWN with a reason; no invented numbers.

## Screenshots-as-text

### `/` (Today), after comps and numbers
```
DRY-RUN · nothing leaves this machine · system RUNNING   (was FROZEN until `mbos panic off`, F-89)
Needs from you (4)
  Patch two drywall holes and a ceiling stain            Needs from you: more evidence
  6x12 enclosed trailer, needs lights + floor            Needs from you: evidence, not archived
  Install video doorbell and three smart switches        Needs from you: customer_screened + scope_verified -> YES
  Zero-turn mower 48in, deck seized                      Needs from you: no comparable sold price
Needs your decision (0)   Nothing waiting.     On hold (0)     Closed / executed (0)
```

### `/item/<doorbell>` (trimmed)
```
Needs from you: customer_screened + scope_verified -> YES
This item is parked: the system cannot recommend it until it has a price to compare with.   <- wrong for a service (F-90)
Add a price I saw  [Make][Model][Sold price][Date][Condition][Where][Link][Note][PIN] [Save this price]
SERVICE smart_home_install · Little Rock, AR · 10 mi · asking $600
Why: More evidence would settle it: a call with the customer and photos or a visit to size the job.
     Expected net about $373 after repair and transport, with $53 of cash at risk.
     YES blocked: composite 59.81 < 60 ; YES blocked: confidence 0.1500 < 0.60
     cheapest decisive evidence: customer_screened + scope_verified -> YES
Class SERVICE_JOB · skill fit 0.85 · Cash situation: UNKNOWN
Recommendation: HOLD   Your decision: No open request is waiting for a decision on this item.
```

### `/item/<trailer>` after the $1,850 comp and a recheck (card text)
```
Ask $950   Opening offer $240   Max acquisition $243   Repair $160  Transport $37  Cash at risk $1,112
Resale: conservative UNKNOWN / likely $1,850 / optimistic UNKNOWN   Net $597   $77/h   16 days to cash
GATE FAIL max_loss_ok: max loss $507.80 exceeds cap $500.00
GATE FAIL cash_ok: cash tied up $1,111.62 exceeds the cash you can fund (cap $500.00)
Asking $950 is $707 above the most you should pay ($243).
RECOMMENDATION: HOLD  A pass here would rest on assumptions, not evidence; gather the missing evidence before discarding it.
```

### `/mission` (after target $1,500, 30 h, fund $500)
```
Recommendation  DEPLOY capital to the legs below. Each still needs your own YES.      <- F-94
Week 2026-10-05 to 2026-10-11   Weekly target $1,500   Hours 30.0 h   about 500 free
Realized $0   Expected (low / likely / high) $-16 / $640 / $1,028   Remaining gap $860   Confidence low
Planner: Probability this plan reaches $1,500 inside 7 days: 0.0000 ... short by about $860
Capital: Protected principal $500 · Earned $0 · Deployed $0 · Available to deploy $500
Best next opportunities (2)  SERVICE_JOB $53 / $-9 $373 $477 / 4.0 d / 0.776 / 5.611 h / MAYBE ... open the card
                             SERVICE_JOB $0  / $-7 $266 $551 / 4.0 d / 0.475 / 6.4334 h / MAYBE ... open the card
Replace if stale  itm_01M4E42QPTJCHQ2C1XY9P8PCBT  itm_01M4E42QS738BKTD9GR7BZBJ79
UNKNOWN (1)  current_cash_context
```

### `/numbers`
```
My numbers: this week   Weekly target $1,500   Hours available 30.0 h   Cash situation about 500 free   Week 2026-10-05 to 2026-10-11
Capital ledger   Protected principal $500 · Earned working capital $0 · Capital deployed $0 · Realized profit $0 · Available to deploy $500
[Fund (USD)][Confirm if over $2,000][PIN][Fund]   [Withdraw (USD)][PIN][Withdraw]   Total funded is limited to $5,000.
```
Before the workaround: "Not saved. the store refused it: permission denied for function set_mission" (F-88).

### `/wanted`
```
5x8 utility trailer   PAUSED  RECOMMEND
trailer · max $900 · 40 mi · keywords 5x8, utility · cosmetics ignored
last change: revision 2: PAUSED (RECOMMEND) by michael      status PAUSED: not running      [Resume] [Cancel]
No current Item matches (4 checked). Recommendation only; nothing was contacted.
```

### `/digest`
```
ACT NOW (alert): 0 · Decide: 0 · Research: 2 · Research before discarding (R13): 1
1 Research SERVICE smart_home_install  Install video doorbell...  research: customer_screened + scope_verified -> YES  ... EV $79.84/h, EV $246.50 ... Value 11.98   (F-95)
2 Research SERVICE drywall_repair      Patch two drywall holes...  research: YES blocked by composite, low confidence (evidence), EV $/h below target
3 Research before discarding (R13) FLIP trailer  PASS on cash_ok, max_loss_ok rests on priors
Not ranked (1): the mower: RESEARCHING: not scored yet (research gaps outstanding)
```

### Other pages
`/summary`: "Do first" list repeats the digest with Value `$12`/`$11`/`$0`; HOLD backlog 0; Source health "Unavailable: MBOS_SOURCE_HEALTH_FILE not set" (F-100). `/holds`, `/outcomes`: "Nothing is parked." / "None recorded yet." `/notes`: "No notes yet." `/intake`: "Start draft" button only. `/ledger`: "chain verified (83 receipts)", newest row `KILL_SWITCH_CHANGED michael PANIC L3 release`.

## Reproduction notes
- Everything ran in `/tmp/a07audit/w` (a detached worktree of the coordinator head; no other lane touched). Helper scripts (HTTP + HTML-to-text) are in `/tmp/a07audit/tools` and are not part of the repo.
- Do not `pkill -f "operator_ui serve"` from the same shell (it matches the shell's own command line).

---

# Re-audit as Michael after wave 2 (G-22)

Date 2026-10-08. Fresh worker, DRY-RUN only. Coordinator head `24e630f`; lane pins at bootstrap: 04 `1ad83f7`, 05 `44a0fb2`, 03 `3dc8a49`, 02 `a2b971d`, 06 `96fb674` (assembly A) and `1a3d928` (assembly B, bootstrapped later; lane 06 pushed in between). Method as G-20: detached worktree, `tools/bootstrap_dev.py --ui-pin`, `mbos worker --fixture fixtures/sources/training_examples.json` (A-41 set), Operator UI as the RUNBOOK prints it (`MBOS_OWNER_DATABASE_URL`, no workaround), every action over HTTP exactly as the browser forms post. Assembly A drove jobs 1-5 and the HOLD path; assembly B (fresh) drove the straight YES. FACT = observed.

## Verdict (G-22): can Michael use this today? YES for the flip path, NOT YET for a held deal or a service lead

Out of the box: no env workaround, system RUNNING, $500 funded, three-line Today header, the $30 TV reaches "Needs your decision" after one comp typed in the UI, and a YES with the PIN runs to `ACTED` (dry-run, audit chain ok). What still blocks a full week of use: a HOLD cannot be turned into a later YES (F-120, P1), and the service lead cannot reach YES because there is nowhere to enter a quote (F-111, known, F-32 is blocked on A-43).

| # | Job | G-20 | G-22 | Ranked reason / evidence |
|---|---|---|---|---|
| 1 | See what matters today | PARTIAL | **PASS** (P2 stale label, F-121) | `/` opens with "Gap to target $1,181 still to earn this week / Cash $500 available to deploy / Best next move". Caveat: "Best next move: Decide: 55 inch LED TV ... ready for your YES or NO" stays after the TV is HELD or EXECUTED, while the same page says "Needs your decision (0)" |
| 2 | Understand the best money opportunity | FAIL | **PASS** (P2 F-122) | `/mission` names legs and what each waits on ("scope_verified: photos or a visit ...") and says HOLD "Nothing is ready to approve" until a YES exists; after the TV is YES it lists TV $36 at risk, net $10/$53/$56, 5 d, chance 0.95. Caveat: after the TV was executed the headline still says "DEPLOY capital to the 1 job marked YES below" with no YES job listed |
| 3 | Create / update / pause a Wanted campaign | PARTIAL | **PASS** (P3 F-124 remains) | create `5x8 utility trailer` (RECOMMEND, receipt `rcpt_01M4F336...`), Edit keeps must-have "clean title" and nice-to-have, saves as revision 2 (max $750, nice "lights, ramp"), Pause -> revision 3 PAUSED, Resume/Cancel offered. Still: "No current Item matches (4 checked)"; nothing is hunting for it (F-97 tail) |
| 4 | See bankroll / cash and set his numbers | PASS w/ P0 | **PASS** | UI worked with the bootstrap's own variable; target $1,500, hours 30, "about 500 free" saved; Today and `/mission` show gap $1,181; ledger Protected $500 / Available $500 / Deployed $0; the card now reads "Cash situation: 500.0" (F-96 fixed) |
| 5 | Understand WHY a deal is worth pursuing | PARTIAL | **PASS** for flips; service lead see job 7 | TV: "Meets your bar: about $86/h against your $65/h flip target, $36 at risk (limit $500). 1 sold comparable puts resale near $92. Asking $30 is $5 below the most you should pay ($35)". Recon: "Not a YES yet ... works up to $277 once the missing evidence checks out ... Asking $300 is $23 above the most you should pay". Mower: archived, PASS on bankroll. Numbers are labelled FACT / INFERENCE / UNKNOWN. Residual: F-123 (same deal, different dollar figures on card vs digest) |
| 6 | Approve / decline / hold one | FAIL | **PARTIAL**: YES and HOLD work, HOLD -> YES is broken (P1 F-120) | Straight YES (assembly B): UI YES with PIN -> `ACTED`, receipts "guard passed (8/8); calling effector dry_run=True", "comms.email.send executed (DRY-RUN)", `mbos audit` ok, no tracebacks. HOLD (assembly A): "HOLD recorded", item listed under On hold and `/holds`. NO not re-run (one pending request only, and a decision is single-use); NO was verified in G-21b (stage 5) on a slightly older head |
| 7 | Know what needs his decision vs input | PARTIAL | **PARTIAL** | Split works and now truthful for flips ("no comparable sold price" + a form). Gap: drywall lead says "Needs from you: more evidence" even after Michael attested scope_verified and customer_screened (worker rechecked by itself, F-109 fixed); the card then says "evidence is not the blocker ... minimum quote for YES $651" and there is no field to enter a quote (F-111). A comp saved with condition "parts" for the mower and the Recon left both on "no comparable sold price" with no message that the price was not usable (F-125) |

G-20 repros now passing: F-88 (UI starts on the owner DSN, no workaround), F-89 (born RUNNING, bootstrap says so), F-90 (items reach a decision; attestation forms per evidence key: scope_verified, materials_priced, customer_screened, repeat_or_referral, remote_verification, price_agreed_in_writing, access_and_schedule_confirmed), F-91/F-92 (worker re-checks by itself within about a minute after a comp or an attestation; no `mbos recheck` run), F-93, F-94, F-95 (partly, see F-123), F-96, F-97 (edit keeps must-have), F-98, F-100 (nav hides unconfigured tabs; `/sources` `/usage` `/preview` are gone from the tab bar), F-101. **$1,500 / $3,000 / stale values:** none on screen; the only $1,500 is the target typed in step 4.

## New findings (continue after F-119)

| ID | Sev | Owner | Tag | Finding | Repro | Recommendation |
|---|---|---|---|---|---|---|
| F-120 | **P1** | 01 (+04) | FACT (symptom, workflow ids); INFER (cause) | **F-116 is not fixed for the real path.** A HOLD on an item whose approval workflow was started by a recheck (every item that needed a comp or an attestation) can neither be woken nor approved. `mbos ping` ("pinged") x3, the UI "Wake now" ("Wake sent. The workflow re-presents the request") and a worker restart changed nothing: item stays `HELD`, no wake receipt. Then UI YES with the PIN says "YES recorded. The item workflow now runs it through the gateway" but the item stays `HELD`, the item page says "No open request is waiting for a decision", and the worker logs `mbos: item ... cannot be APPROVED without a YES/MODIFY approval receipt since it entered AWAITING_APPROVAL` (3 tracebacks). INFER: `ping`/wake send to `item_workflow_id(item)` but the pending workflow is `recheck:<item>:<epoch>-1` (`item_lifecycle`), so the message never arrives (the system DB shows exactly that id PENDING). The decision path survives only because it re-polls. | Assembly A: add TV comp in the UI, wait for YES, UI HOLD (preset), `mbos ping <item>` or UI Wake, then UI YES. | Send ping/wake to the workflow that is actually parked (look it up), or make the hold loop poll the item state like the decision path; refuse to say "YES recorded ... runs it" when the request is not approvable; add a test that holds an item whose workflow came from a recheck. |
| F-121 | P2 | 06 | FACT | Today "Best next move" is stale: it says "Decide: <TV> is ready for your YES or NO" while the TV is HELD (Needs your decision 0, On hold 1) and again after it is EXECUTED (Closed 1). | After HOLD or after YES, open `/`. | Compute the next move from open requests only; after an execution say what is next (record the outcome, or the next best item). |
| F-122 | P2 | 01 mission / 06 | FACT | After the only YES leg was executed, `/mission` still says "DEPLOY capital to the 1 job marked YES below. Each still needs your own YES" and lists no YES job; cash at risk $36 still shown. | Assembly B: YES the TV, open `/mission`. | Recompute from open requests; show executed legs as "done, awaiting outcome". |
| F-123 | P2 | 01 digest / 03 | FACT | F-95 only partly fixed: names are consistent now, but one deal still has two dollar figures. Drywall lead: card/`/mission` net $266 vs `/digest` and `/summary` "Expected profit $175.57". Recon: card net about $311 vs `/summary` $239.03. | Compare `/item/<id>`, `/mission`, `/digest`, `/summary`. | Say on each page what the figure is (net vs probability-weighted EV) or show one. |
| F-124 | P3 | 06 / 02 | FACT | Wanted still only filters Items already in the database ("No current Item matches (4 checked)"); the page does not say nothing is searching. (F-97 tail.) | Create a campaign, open `/wanted`. | One line: "no source is hunting for this yet". |
| F-125 | P2 | 06 / 03 | FACT (symptom); INFER (cause) | A comp saved with Condition "parts" for the mower ($250) and the Recon ($450) produced the "Price saved" banner and a recheck, yet both stayed "no comparable sold price" with the same form and no explanation; the same items resolved when the same form was filled with condition "used" ($700 / $1,050). INFER: condition-mismatched comps are discarded silently. | Assembly B: `/item/<mower>` comp with condition parts, wait two minutes. | After the recheck say "your price was not used because ..." or accept it with a haircut. |

Carried open (not re-filed): F-111 (P1, service lead needs a quote; C-28 landed in the engine, F-32/A-43 are the UI half), F-112, F-114, F-115, F-117, F-119.

## Screenshots-as-text (G-22)

### `/` on a fresh bootstrap (assembly A)
```
DRY-RUN · nothing leaves this machine · system RUNNING
Gap to target UNKNOWN set your weekly target on My numbers      Cash $500 available to deploy
Best next move  Give the system what it is waiting for on Patch two drywall holes and a ceiling stain : scope_verified: photos or a visit to size the job.
Needs from you (4)  TV: no comparable sold price | mower: no comparable sold price | Recon: no comparable sold price | drywall lead: more evidence
Needs your decision (0)   On hold (0)   Closed / executed (0)
```
### `/` after the TV comp, target $1,500 and a worker re-check (no terminal command)
```
Gap to target $1,181 still to earn this week     Cash $500 available to deploy
Best next move  Decide: 55 inch LED TV, works great, $30 firm, today only is ready for your YES or NO.
Needs your decision (1)  FLIP other_asset  System says YES  pending_approval · expires in 72.0h
   EV $53  $86/h  confidence 0.95  irreversible   Proposed: Ask the seller about the 55 inch LED TV ... comms.email.send
```
### `/item/<TV>` after HOLD, Wake, then YES (F-120)
```
Recommendation HOLD   Parked at Michael's request; it wakes on the condition he set and never acts on its own.
Your decision  No open request is waiting for a decision on this item.
(banner after YES) "YES recorded. The item workflow now runs it through the gateway (dry-run); watch the receipts below."
```

---

# Third audit as Michael: the full money loop (G-23)

Date 2026-10-08. Fresh worker, DRY-RUN only (nothing sent, bought, published or contacted; both throwaway clusters stopped). Coordinator head `ccbb265`; lane pins at bootstrap: 04 `1ad83f7`, 05 `44a0fb2`, 03 `3dc8a49`, 02 `a2b971d`, 06 `6173c74` (includes F-32, F-33, F-34, F-35, F-36). Method as G-22: detached worktrees, `tools/bootstrap_dev.py --ui-pin`, `mbos worker --fixture fixtures/sources/training_examples.json`, Operator UI, every action posted over HTTP like the browser forms (CSRF + nonce + PIN). Assembly A (:8794): jobs 1-5, 7, mower, Recon, BBQ trailer, first HOLD attempt. Assembly B (:8795, fresh): the money loop, second HOLD attempt, Wanted. FACT = observed.

## Verdict (G-23): can Michael use this today? YES for a flip from comp to closed profit; NOT YET for a HOLD he later says YES to

The whole money loop works on the TV, with ledger movements that match: comp -> YES with PIN -> dry-run `ACTED` -> "I bought it" ($30 deploys) -> outcome sold ($92, principal back, +$62 earned). The drywall lead now reaches YES from a typed quote ($700). The BBQ trailer is added from the My assets page and its five-path card computes from his rough ranges. One P1 remains: **a HOLD followed by a YES still leaves the item HELD** (F-126, A-48 does not fix it on the real path; 2 of 2 attempts), and the audit's conformance check goes red after the quote is saved (F-127).

| # | Job | G-22 | G-23 | Evidence |
|---|---|---|---|---|
| 1 | See what matters today | PASS | **PASS** (P2 F-129) | `/` opens "Gap to target $1,181 / Cash $500 available / Best next move"; after the TV was executed the next move named the drywall hold, not the stale "Decide: TV" (F-121 fixed) |
| 2 | Understand the best money opportunity | PASS | **PASS** | `/mission` after execution: "DONE for now. 1 job executed, awaiting the outcome" (F-122 fixed); after the sale the position moved. Residual: "Cash at risk $36 of $470 available" counts the $30 already deployed (F-132) |
| 3 | Create / update / pause a Wanted campaign | PASS | **PASS** (F-131) | create `5x8 utility trailer` (receipt `rcpt_01M4FDMC7BADVPVS3CSNCPC50F`), edit = revision 3 (max $750, "lights, ramp"), pause = revision 2 PAUSED. "3 current Items checked" with no line saying nothing is hunting (F-124 claimed fixed, still absent) |
| 4 | See bankroll / cash and set his numbers | PASS | **PASS** | target $1,500, 30 h, "about 500 free" saved; gap $1,181; ledger moves in the loop below |
| 5 | Understand WHY a deal is worth pursuing | PASS | **PASS** (F-128, F-130) | TV and Recon cards read well; Recon "Not a YES yet: about $64/h ... Buying at or below $202 would clear it"; the parts-comp reason (F-125) not re-run. New: status line contradicts the card (F-130) |
| 6 | Approve / decline / hold one | PARTIAL | **PARTIAL** | YES with PIN (TV) -> `ACTED`, receipts below. NO (drywall, assembly A) -> "NO recorded; the opportunity is archived". HOLD recorded and listed; **wake then YES does not reach ACTED** (F-126, P1) |
| 7 | Know what needs his decision vs input | PARTIAL | **PASS** (F-127, F-130 aside) | drywall: scope_verified + customer_screened typed; at $500 "a quote of $651 or more would clear the bar" (stays input); at $700 -> "Needs your decision" YES, EV $310, $85/h (F-111 fixed). Recon: fault_identified + condition_verified typed -> MAYBE naming "walk-away price $202" (mower archived: PASS) |

## The money loop (assembly B, TV `itm_01M4FD9SYTJ7ZRJN6MTKH41MDZ`)

| Stage | Result | Receipt / evidence | Ledger (protected / earned / deployed / profit / available) |
|---|---|---|---|
| 0 Before | | | $500 / $0 / $0 / $0 / **$500** |
| 1 comp $92 typed, worker re-check | **PASS** | TV reaches "Needs your decision (1)", YES, EV $53, $86/h | unchanged |
| 2 YES with PIN | **PASS** | `rcpt_01M4FDG78T60SVE6WHF9EN9P9Y` APPROVAL_DECIDED (Michael) | unchanged |
| 3 dry-run action | **PASS** | `rcpt_01M4FDG7GHWW4S9JM3WDJG8FHB` BUDGET_COMMITTED (email, $0), `rcpt_01M4FDG7GW3AQSVK6KZDF74WX2` ACTION_EXECUTED `comms.email.send (DRY-RUN)`; item `ACTED` | unchanged (a send moves no capital) |
| 4 "I bought it" $30 | **PASS** | `rcpt_01M4FDK8M1YJH4F7131EDR4D9T` ACTION_PROPOSED, `rcpt_01M4FDK8M72F0B1798DGW52RZP` BUDGET_COMMITTED (purchase, $30, human) | $500 / $0 / **$30** / $0 / **$470** |
| 5 outcome flip_sold (revenue $92, cost $30) | **PASS** | `rcpt_01M4FDKJKWKQRCVMFD918863KX` OUTCOME_RECORDED (`outc_01M4FDKJKSXJK3QMYFYYQ31SGV`), `rcpt_01M4FDKJM4S699T0XGM2TQMN6W` ITEM_STATE_CHANGED | $500 / **$62** / **$0** / **$62** / **$562** |
| 6 second close of the same item | **PASS** | "already closed: its capital was returned ... a second 'flip_sold' is refused and nothing moved" (F-115 fixed) | unchanged |
| 7 chain | **PASS** | `mbos audit`: chain ok (112 receipts), provenance ok, dry_run ok (1 effector receipt); **conformance not ok** (F-127) | |

HOLD -> wake -> YES (assembly B, drywall lead at $700): HOLD `rcpt_01M4FDG64NH2G4E2M4G690K1KS`; UI "Wake now" ("Wake sent. The workflow re-presents the request"); then YES `rcpt_01M4FDHJYXFXQFC8BH9D1F8MCR`. Result: item stays `HELD`, request goes to `approved`, no ACTED. **FAIL.** Assembly A repeated it on the TV (HOLD, Wake, YES; `mbos ping` and a worker restart changed nothing).

BBQ trailer (assembly A, `/assets/asset-83273bdf`): added with a $1,800 sunk basis and a past tow (INFERENCE); with no figures all five paths read UNKNOWN and name the exact missing inputs; with example ranges the card says "System leans THEMED_VALUE_ADD_FLIP (range midpoints; roadworthiness is INFERENCE)": SELL_AS_IS $0 cash, net $500-$900; MINIMAL $150-$300 cash, net $900-$1,650; THEMED $500-$900, net $1,300-$2,700, 30-60 days; CONVERT net $900-$2,200; KEEP $250-$600 use value; structural risk UNKNOWN; nothing marked verified. **PASS** with F-133, F-134.

## New findings (continue after F-125)

| ID | Sev | Owner | Tag | Finding | Repro | Recommendation |
|---|---|---|---|---|---|---|
| F-126 | **P1** | 01 (+04) | FACT (symptom, workflow ids); INFER (cause) | **A-48 does not fix HOLD -> wake -> YES on the real path.** After HOLD, "Wake now" says the request is re-presented but "Needs your decision" stays 0 and the item stays `HELD`. A later YES with PIN says "YES recorded", moves the request `held -> approved`, and the worker logs `item ... cannot be APPROVED without a YES/MODIFY approval receipt since it entered AWAITING_APPROVAL` (the `recheck:<item>:<epoch>` / `item_lifecycle` workflows end ERROR; a `followup:<areq>` workflow also ERRORs). The UI then files the stuck item under "Closed / executed" as "approved" while Today says "on hold. Wake it", and `/holds` is empty. 2 of 2 attempts (TV on A, drywall on B); `mbos ping` and a worker restart do not help. INFER: the wake reaches a gate workflow that does not return the item to AWAITING_APPROVAL, so the later decision has no live gate; A-48's e2e test passes on a path the UI does not take. | Assembly B: quote $700 -> HOLD (preset new_info) -> Wake now -> YES; `mbos items`; read the worker log. | Reproduce through the UI HTTP path in the e2e test (not `spine` calls); on wake, re-enter AWAITING_APPROVAL on the active gate and re-present a pending request; a YES on a held request must either reach ACTED or fail visibly. Put a stuck `approved`-but-HELD request in no list silently. |
| F-127 | **P1** | 03 / 01 | FACT | `mbos audit` conformance goes red after Michael saves a quote: `item ...: research/5: Additional properties are not allowed ('entered_by', 'value' were unexpected)`. The `quote:amount_usd` research entry (C-28) carries fields the frozen Item contract's `research` schema does not allow. This is F-102 again, caused by the new quote path. Chain, provenance and dry-run checks stay ok. | Save a quote on the drywall lead, run `mbos audit`. | Either carry the human value in an allowed field or ADR a contract bump; add a conformance assertion after a quote in the C-28/F-32 tests. |
| F-128 | P2 | 06 | FACT | My assets: free-text "1800 paid in 2023" is read as a range, so the card says "Sunk basis ... $1,800-$2,023". A year in the sentence became money. The tow description is stored as text, so the intake is half typed, half guessed. | `/assets`: basis "1800 paid in 2023". | Ask for an amount box and a date box, or show how the text was parsed and let him correct it. |
| F-129 | P2 | 01 | FACT | Saving an attestation and then a quote (or two inputs a minute apart) starts two `recheck:` workflows for the same item; both ERROR (`duplicate key ... provenance_pkey` from `record_research`/`record_provenance`). This is F-91 on a new path; the later state is still reached, but the worker logs tracebacks and the UI says nothing. | Assembly B: attest scope_verified, attest customer_screened, then quote within about 2 min. | Coalesce rechecks per item (one in flight, one queued) and make `record_research` idempotent. |
| F-130 | P2 | 06 / 03 | FACT | Recon after Michael attested fault and condition: Today and the card header still say "Needs from you: more evidence" while the card body says "evidence is not the blocker: no missing evidence item changes the verdict" and gives the real condition (walk-away $202 vs asking $300). The item page still shows "This item is parked: the system cannot recommend it until it has a price" even though a $1,050 comp is on the card. | Assembly A: comp, then two attestations on the Recon. | Status line follows the verdict: "Not a YES at $300; it would be at $202 or less". |
| F-131 | P3 | 06 | FACT | F-124 is not fixed: `/wanted` with a campaign still reads "3 current Items checked" and nowhere says no source is hunting for it. | Create a campaign, open `/wanted`. | One line under the title. |
| F-132 | P3 | 06 / 01 | FACT | After "I bought it" ($30 deployed, available $470), `/mission` shows "Cash at risk $36 of $470 available" and still counts the TV as an opportunity's risk; the $30 is counted both as deployed and as risk. | Assembly B: buy, open `/mission`. | Show deployed capital separately from the cash still at risk. |
| F-133 | P2 | 03 / 06 | FACT | The five-path card shows net, cash, hours and days but not the per-path profit per hour or profit per incremental dollar that C-30 specifies, and the lean (THEMED) follows range midpoints of net only: 30-60 days and 20-30 own hours do not weigh against Michael's weekly $/h target. Structural risk reads UNKNOWN for every path even with the checklist unanswered (honest, but no "answer these 3 first" ordering). | Enter the example ranges at `/assets/<id>`. | Add $/h and per-dollar columns; name the one or two checklist answers that would change the lean. |
| F-134 | P3 | 06 | FACT | The figures form rejects "Sep-Nov" with a message ("type month numbers 1-12 separated by commas") but the page re-renders without the other typed figures' confirmation; the first full submit therefore looked silent in my script. The message appears only at the top. | `/assets/<id>` with tailgate months "Sep-Nov". | Keep the typed values and mark the bad box. |
| F-135 | P3 | 06 | FACT | The outcome form and the HOLD form carry no PIN box; only YES, I bought it and the evidence forms do. Recording a sale moves capital and profit. INFER: a session already authenticated by an earlier PIN is enough; if so, say it. | Read the outcome form fields. | Decide whether a sale that moves the ledger needs the PIN, and state the rule on the form. |

Fixed since G-22 (verified here): F-111 (quote form; $500 stays input, $700 reaches YES), F-114 (capital deploys when he records the purchase), F-115 (duplicate close refused), F-121, F-122, F-123 (labelled figures: "Priority score" and "Expected profit, weighted by chance"). Not re-run: F-125 parts comp; NO on a pending flip (NO on the drywall lead was run). **$1,500 / $3,000 / stale values:** none on screen; the only $1,500 is the target typed.

Health: `mbos_qa spine --rc` 105 passed, 0 failed (3 skipped); `mbos_qa card` 671 passed, 0 failed (mbos pin 71d5cdb).
