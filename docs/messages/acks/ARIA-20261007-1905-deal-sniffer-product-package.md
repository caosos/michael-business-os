# ACK: ARIA-20261007-1905-deal-sniffer-product-package

- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARIA-20261007-1905-deal-sniffer-product-package.md`
- **Package:** `docs/product/DEAL_SNIFFER_START_HERE.md` (copied verbatim onto this branch, added to the onboarding path in `START_HERE.md`)
- **Classification:** OWNER_INPUT + TASK_REQUEST + PROJECT_FACT
- **Disposition:** **TASKED** (scope decided in ADR-0013; seams queued; nothing built beyond seams)
- **Acked by:** Agent 01, 2026-10-08
- **Authority check:** product/design direction only. No spend, contact, bid, payment, publishing or deployment was taken or enabled; everything queued is DRY-RUN and additive.

## Reconciliation against repo truth
| Package item | Repo truth today | Disposition |
|---|---|---|
| No universal profit floor; capital velocity | ADR-0012; card fields done; engine still gates at 150/100 | already tasked: **C-19** (03, claimed), C-20, F-17, G-10 |
| Weekly Money Mission, $500 protected principal, capital ledger | absent | **A-23** schema (01), **C-21** planner (03), **D-18** ledger (04), **F-18** page (06). Weekly target is an example, so it is UNKNOWN until Michael sets it: MICHAEL_DECISIONS #10 |
| Richer classes (SERVICE_JOB, OTHER_OPPORTUNITY) and tags | 4 flip classes on the card | **A-24** (01), **B-21** tags (02) |
| Canonical inventory + audience views | absent | **A-25** schema + truth-preserving lint (01), **F-19** renderer (06) |
| Campaigns / wanted objects, autonomy levels | absent | **A-26** schema (01), **B-20** matcher (02), **E-17** policy: autopilot denied by default (05) |
| Conversational intake | absent | **A-27** deterministic missing-question engine (01), **F-20** front door (06) |
| Valuation | comps exist for flips | **A-26** schema, **C-22** interface + flip valuator, homes UNKNOWN (03) |
| Reputation, credentials, payments | `money.payment.*` granted to nobody | **E-18** seams (05); no capability granted |
| Jurisdiction packs | absent | **E-19** format + evaluator, synthetic sample only (05) |
| Operator UI implications | card page + digest | F-17, F-18, F-19, F-20 |
| Adversarial verification | | **G-11** (07) |
| Listing age, relist, stale risk, seller intelligence | done (B-15) | no new work |
| AI "possible finished look" | | out of scope; stays future, imagery labelling rule recorded in ADR-0013 |

## Scope decision
ADR-0013: Level 1 only is built; Levels 2-3 get seams so they can be added without refactoring the core. No frozen contract changes; new objects are additive schemas pinned by `FROZEN.sha256.json`.

## Runtime concern (all seven agents idle at once)
Accepted as an operations priority: **A-22** `tools/foreman.py` (read-only idle/stale detector with a wake line). It cannot start sessions; scheduling it on the host is OWNER_ACTIONS D2. Repo-side, I replaced the stale queue and ACTIVE_WORK with current heads and assigned work to every idle agent.

## Remaining blocker
None for dispatch. Owner decisions that only unlock numbers (not work): #9 cash context, #10 weekly target and hours.
