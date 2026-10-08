# Owner decision packets (Michael only)

Updated 2026-10-08 by Agent 01. **Nothing here blocks the dry-run MVP.** Each packet: the exact decision, what the system uses today, my recommendation, cost/risk, what it unblocks, whether it can wait. Source of truth for the long text is `docs/status/MICHAEL_DECISIONS.md`; this page is the short form. Everything stays DRY-RUN until you decide #4/#5 and the release gate is green.

**Canon used by the system today:** protected principal **$500** (your stated bankroll, `config/operator_profile.v1.json` `mission.protected_principal_usd`); earned working capital is tracked separately; no universal profit floor (ADR-0012). The old $1,500 per flip / $3,000 total defaults are superseded (tasks C-24, E-23).

## Decisions

| # | Decision | Today's default | Recommendation | Cost / risk | Unblocks | Can wait? |
|---|---|---|---|---|---|---|
| 10 | Your **weekly income target** and **hours per week** you can work | both UNKNOWN; the Mission page shows the gap as UNKNOWN (never an invented target). Enter them on the "My numbers" page | Enter your real numbers (the $1,500 in the product package was an example) | none; changeable any time, every change is receipted | A real projected week, remaining gap, and a plan sized to your hours | Yes, but this is the single most useful number to give |
| 9a | **Your cash situation now** (free text or amount) | UNKNOWN | State it on "My numbers"; update when it changes | none | The card can say "good asset, wrong buy today" using your actual lock-up tolerance | Yes |
| 9b | Confirm **deal-class thresholds** | MICRO <= $100 and <= 3 days; QUICK_TURN <= 10 days; CAPITAL_INTENSIVE >= $750 or >= 45 days (provisional) | Lower CAPITAL_INTENSIVE's cash line to about **$300** (60% of the $500 bankroll), because $750 is above your whole bankroll and the class could only trigger on duration | Wrong thresholds only change labels and ranking, not what you may approve | Correct class labels and capital-velocity ranking | Yes |
| 1 | **Cash at risk**: max per flip and max total active | $500 per flip, $500 total (= the protected principal). Earned working capital raises the live limit through the capital ledger | Keep $500/$500 until the first closed flip shows earned capital; the ledger then lifts the live cap automatically | A higher cap risks more than your protected bankroll | Real YES/MAYBE/PASS cash gates | Yes |
| 2 | **Profit per hour**: floor and target | $40/h floor, $65/h flips, $75/h services (provisional). These are RATES, not a dollar profit floor | Keep until you have 5-10 real outcomes, then calibrate from results | Too high rejects good quick flips; too low wastes your time | What counts as a good deal | Yes |
| 6 | **Service pricing**: quote rate and minimum charge | $85/h, $125 minimum (placeholders) | Set your real rate; the system only drafts, you approve every quote | A wrong quote is caught at your approval step | Service quotes it drafts | Yes |
| 3 | **Higher-risk sources** (ToS-adverse, browser automation: Marketplace, GovDeals, HiBid) | Official sources only | Keep official-only; revisit per source after the first live run | ToS/ban risk and legal exposure | More listing coverage | Yes |
| 4 | **Outbound AI calling/texting** posture and counsel (TCPA, AI-voice consent) | Disabled | Keep disabled; get counsel before any live voice/SMS | Legal liability | Live seller/customer contact | Yes (gates all live contact) |
| 5 | **Approval delegation** | None: everything asks you | None during the MVP | Delegation widens what runs without you | Narrow pre-approved actions | Yes |
| 7 | Reselling items **given away free** in gift groups | Flagged needs_review, case by case | Keep case by case | Group rules / reputation | Free-item flips | Yes |
| 8 | Apply for **eBay Marketplace Insights** (sold prices) | Sold comps entered manually | Apply when you want live sold comps (external account action, your call) | Time; approval not guaranteed | Sold-price comparables | Yes |
| 11 | Where **off-box backups** go | None: one machine holds everything (RPO 24 h for host loss) | **Encrypted cloud object storage** if you will open an account, else another machine you own; a USB drive only as a stopgap | A few $/month (cloud); backups hold seller contact values so they MUST be encrypted | D-09b/D-19/D-20: continuous off-box copy | **No: this is the biggest real risk** (lost disk = lost everything) |
| 12 | **CRM projection** (Twenty) | Not built | Skip for now; the Operator UI covers your needs | Extra service to run | D-21 | Yes |
| 13 | Your **licences held** (e.g. residential, electrical) for service-job eligibility | UNKNOWN; jurisdiction packs are synthetic samples | Tell the system what you hold; real, cited, dated packs get built from it | Wrong claims could mis-qualify jobs, so a human reviews every pack | E-20/E-21: license gate on service offers | Yes |

## Operator (host) actions, not decisions

| Action | Why | Can wait? |
|---|---|---|
| `sudo loginctl enable-linger michaelos` | The database does not start by itself after a reboot without it | Do it soon; one command |
| Install Podman (and optionally gVisor) | Reboot test D-22; sandbox spec E-22 | Yes |
| Schedule `tools/foreman.py` (cron/systemd, every 10-15 min) | It reports idle lanes with READY work; sessions are now started per task, so nothing idles, but the check is cheap | Yes |
| Credentials: eBay keyset; GSA, Trash Nothing, SAM.gov keys; an alert mailbox | The first live read-only run (B-12) | Yes (dry-run works on fixtures) |
| Set `MBOS_OWNER_DATABASE_URL` for the human CLI/UI processes; run the workflow worker WITHOUT it | R14: the workflow process must not be able to approve or move capital | Before any live use |
