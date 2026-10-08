# Operator audit as Michael (G-20)

Date 2026-10-08. Fresh worker, DRY-RUN only (nothing was sent, bought or published). Coordinator head `edda153` (A-39 merged, F-28 on 06 `3a30680`). Lane D `4a11f1b`, lane E policy `44a0fb2`, lane 03 `44e1beb`, lane 02 `55a7e19`.
Method: a detached worktree of the coordinator head, `tools/bootstrap_dev.py --ui-pin audit-pin`, `mbos worker --fixture fixtures/sources/illustrative.json` (long-running), Operator UI started as the RUNBOOK says, then every action done over HTTP exactly as the browser forms post (CSRF + nonce + PIN, redirects followed by hand). Pages below are HTML rendered to text (screenshots-as-text), trimmed. FACT = observed; INFER = reasoned.

## Verdict: can Michael use this today? NO

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
