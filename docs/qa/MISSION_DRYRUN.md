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
