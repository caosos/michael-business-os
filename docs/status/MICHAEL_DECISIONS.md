# Michael Decisions — Business OS

Status: Round-One reconciliation

These are the only owner decisions that materially affect policy or economics. Technical choices that are reversible are being handled by the coordinator.

> **Decision support (Agent 03, C-09):** `origin/research/agent-03-economics:docs/research/agent-03-sensitivity-michael-decisions.md` shows how today's verdicts change across cash caps and $/h settings. The configuration itself is unchanged.
> - The flip target is the most sensitive setting.
> - The cash cap mainly binds on vehicles.
> - Decide **#2 and #6 together**: the service target and the quote rate are coupled.

## 1. Cash-at-risk policy
Need:
- maximum cash committed to one flip
- maximum total cash tied up across active flips

This becomes a hard governance limit.

Can be left conservative by default for the first dry-run build.

## 2. Time-value target
Need eventually:
- minimum acceptable net profit per Michael-hour
- preferred target profit per Michael-hour

This controls YES/MAYBE/PASS thresholds.

The engine can begin with provisional config and be calibrated from real results.

## 3. Higher-risk source access
Should the system ever use ToS-adverse/internal-endpoint/browser automation for high-value sources such as Marketplace/GovDeals/HiBid when no sanctioned API exists?

Recommended policy:
- official/sanctioned sources first
- isolate higher-risk collectors
- no block/CAPTCHA evasion after an explicit block
- require explicit enablement per source

No decision required tonight.

## 4. Outbound AI calling/texting
Before live outbound AI voice/SMS to sellers/customers, decide legal-risk posture and whether to obtain counsel on TCPA/artificial-voice consent questions.

Recommended default:
KEEP DISABLED during MVP.

## 5. Approval delegation
Initially every external commitment requires Michael.

Later decide which narrow actions may be pre-approved, such as:
- neutral post-job review request
- capped follow-up reminder
- low-cost/reversible marketing action

Recommended default:
NO DELEGATION during MVP.

## 6. Service pricing (raised by Agent 03; not blocking)
Needed eventually:
- the all-in service quote rate (placeholder **$85/h**)
- the minimum service charge (placeholder **$125**)

These set the quotes the system drafts for service leads. The dry-run MVP uses the placeholders, and every draft is still shown to Michael before anything is sent.

## 7. Reselling items given away for free (raised by Agent 02; not blocking)
Some community gift groups, such as Trash Nothing, forbid reselling gifted items.

Should the system ever propose flips of free items from these groups?

Default: these items are flagged `needs_review`, and nothing is pursued without your explicit YES on each one.

## 8. eBay Marketplace Insights access (optional)
Applying to eBay's Limited Release program would give the system sold-price comparables. Applying is an external account action, so it is your call. Until then, sold comps are entered manually.

## 9. Deal classes and your cash situation (raised by Agent 01; not blocking)
Standing rule recorded from your training: **no universal profit floor** (ADR-0012). To classify deals, Agent 01 proposed these starting thresholds from your examples (they are data in `config/operator_profile.v1.json`):
- **MICRO_FLIP:** at most $100 cash at risk and back within 3 days (a $30 TV that sells in an hour)
- **QUICK_TURN:** back within about 10 days
- **CAPITAL_INTENSIVE_FLIP:** $750 or more at risk, or 45 or more days to cash (a mower bought late in the season)
- everything else: STANDARD_FLIP

Please confirm or change them, and tell the system your current cash situation (how tight funds are right now), since that decides whether a good asset is the right buy today. Until you do, the card shows the class as a recommendation and the cash context as UNKNOWN.

---

## Decisions already resolved technically

Michael does NOT need to choose:
- Python vs TypeScript → Python
- Postgres vs CRM as authority → Postgres
- DBOS vs Temporal for MVP → DBOS
- MCP vs custom tools → MCP
- n8n as core vs edge → edge only
- CRM choice for MVP → none required

## 10. Weekly Money Mission inputs (raised by Agent 01 from Aria ARIA-20261007-1905; does NOT block the dry-run MVP)
- **Decision:** the real weekly income target and the hours per week Michael can work. The package's $1,500 is an example, not an instruction. The $500 protected principal is already Michael's stated bankroll.
- **Why:** the mission planner (C-21) and the Mission page (F-18) need them. Until set they are UNKNOWN and the planner reports the gap as UNKNOWN; it never invents a target.
- **Recommended default:** `weekly_target_usd: null`, `hours_available: null` in `config/operator_profile.v1.json`; Michael sets them when ready (same place as `current_cash_context`, #9).
- **Blocked:** a numeric projected week. **Continues:** all schemas, planner, ledger and UI against fixtures.

