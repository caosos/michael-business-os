# Owner question: where do the off-box backups go? (blocks D-09; one decision, plus one command)

**Asked by:** Agent 04 (State) · **Date:** 2026-10-07 · **Status:** OPEN, needs Michael.

## The decision
Pick **one off-box destination** for the database backups (dumps, receipt-chain exports and anchors, artifact files, and continuously archived WAL).

## Why it matters (FACT unless marked)
- The business state is on one machine: the EliteDesk. **Today a lost disk, a theft or a failed SSD loses everything since the last copy.** There is no off-machine copy yet, and the nightly dump and the anchor log currently live on the same disk.
- The receipt ledger is tamper-evident, but tamper-evidence is useless if the only copy of the chain and its anchors dies with the host.
- RECOMMENDATION: RPO 15 minutes and RTO 4 hours (the coordinator default). Today's real numbers are **RPO 24 h** (the nightly dump) for host loss, and 0 for a power cut or crash.
- Getting to RPO 15 min needs WAL shipped to the destination continuously, so the destination has to be reachable most of the time.
- The backups contain **raw seller contact values** (phone numbers and emails, in the consent ledger). **Whatever you choose must be encrypted before it leaves the machine**, and the key must be kept somewhere that is not the same box.

## Options
| | Option | Rough cost | RPO reachable | Notes |
|---|---|---|---|---|
| A | **Another machine you own** (NAS, a second PC) over SSH | $0 | 15 min if always on | Simplest; protects against disk loss, but not against a fire or theft at the same address |
| B | **Encrypted cloud object storage** (Backblaze B2 or S3-class) | a few $/month at this size | 15 min | Protects against site loss; needs an account and a card (your decision) |
| C | **External USB drive**, rotated by hand | one-off ~$60 | 24 h (manual) | Cheapest; depends on you remembering; not continuous |
| D | **Second internal disk** in the EliteDesk | one-off ~$50 | 15 min | Does **not** count as off-box: it survives a disk failure but not a theft, fire or power surge |

**Recommended default:** **B (encrypted cloud) if you are willing to open an account, otherwise A.** Use **D or C only as an interim stopgap**, not as the answer.

## What is blocked until you decide
- D-09: continuous off-box WAL shipping, and the restore drill **from** the off-box copy (full D1/RPO 15 min).
- Honest host-loss recovery. Until then I can only promise recovery from process or OS crashes.

## What continues in parallel (no decision needed)
- I'm building and proving the point-in-time-recovery mechanics against a **local directory**. Swapping in the real destination later changes one setting.
- The existing nightly dump, chain anchor and fresh-cluster restore drill keep working.

## Also needs you (one command, not a decision)
- `sudo loginctl enable-linger michaelos`: without it, the database does not start on its own after a reboot (the reboot plan in `docs/state/RUNBOOK-STATE.md` §3 assumes it).
