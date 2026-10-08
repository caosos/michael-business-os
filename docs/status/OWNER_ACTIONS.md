# What only Michael (or the operator) can do

Everything else is being built and tested by the agents, DRY-RUN only. This is the single list of things that need a human.
Last updated: 2026-10-07 by Agent 01. Nothing here blocks the dry-run MVP; each item unlocks something.

## A. Decisions (details in `docs/status/MICHAEL_DECISIONS.md`)
| # | Decision | Unlocks | Default until decided |
|---|---|---|---|
| 1 | Cash at risk per flip and in total | real thresholds for YES/MAYBE/PASS | $1,500 per flip, $3,000 total (data) |
| 2 | Profit per Michael-hour: floor and target | what counts as a good deal | $40 floor; $65 flip / $75 service |
| 6 | Service quote rate and minimum charge (decide with #2) | service quotes the system drafts | $85/h, $125 minimum |
| 3 | Higher-risk source access (ToS-adverse, browser automation) | Marketplace / GovDeals / HiBid | official sources only |
| 4 | Outbound AI calling/texting posture and legal counsel | live seller/customer contact | disabled; dry-run only |
| 5 | Approval delegation | narrow actions without asking you | none; everything asks you |
| 9 | Confirm deal-class thresholds (micro / quick / capital-intensive) and state your current cash situation | the system can say whether a good asset is the right buy today | provisional thresholds; cash context UNKNOWN |
| 7 | Reselling items given away free in community gift groups | Trash Nothing flips | flagged for review; case-by-case YES |
| 8 | Apply for eBay Marketplace Insights (sold prices) | sold-price comparables | sold comps entered manually |

Agent 03's sensitivity report (`docs/research/agent-03-sensitivity-michael-decisions.md` on its branch) shows how today's verdicts change across #1, #2 and #6.

## B. Credentials and accounts (agents never create these)
Full checklist: `docs/runbooks/first-live-run-checklist.md` on `research/agent-02-opportunity`.
- eBay developer keyset (App ID, Cert ID): live eBay discovery. Then the first live run confirms the field names.
- GSA Auctions, Trash Nothing and SAM.gov keys; an inbox for alert e-mails (GovDeals, PublicSurplus, EstateSales.NET).
- CPSC and NHTSA need no key.

## C. Your own knowledge (the best data the system can get)
- Enter what you know about specific makes and models: `mbos note add --make .. --model .. --kind .. --statement ..` (the Operator UI form is task F-14). It shows on cards as your recommendation. No elementary advice; name the model.
- Confirm facts on `config/operator_profile.v1.json` (trailer not owned, borrowed trailer possible, truck capacity). The card never assumes a borrowed trailer is available.

## D. Host / operator tasks (outside the repo)
| Item | Why |
|---|---|
| Fix `~/bin/mbos-agent` git identity (enable `extensions.worktreeConfig`, set identity per worktree) | the shared git config signs every commit as the last-launched agent (receipt: `docs/receipts/2026-10-07-provenance-correction-commit-authorship.md`) |
| An off-box backup target | point-in-time recovery and restore drills (D-09) |
| Install Podman or a sandbox runtime (`runsc`, Podman, Docker or E2B) if model-written code will ever run | none installed; not needed for the dry-run MVP (05's checker I1–I8) |
| EIN / entity status, business name, service area, Google category | A2P 10DLC, Google Business Profile; only when marketing or SMS goes live |

## D2. Runtime foreman (Aria 1905; host-side, outside the repo)
- The written foreman loop cannot restart a session that has stopped. After A-22 lands, schedule `tools/foreman.py` (read-only) on the host (cron or a systemd timer, every 10-15 min) and use its `--wake-text` output to resume any agent it reports idle. Agent 01 cannot start or wake sessions itself. Nothing in this is an external action; it only reads GitHub.

## E. Not yet possible (waiting on a build, not on you)
- Seeing NEGOTIATING / QUALIFIED on the card needs inbound communications (ADR-0009 item 11).
- Live sends of any kind stay disabled until #4 and #5 are decided and the release gate is green.
