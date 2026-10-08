# Receipt: provenance correction, commit authorship on `research/agent-04-state` (append-only; history NOT rewritten)

- **Date:** 2026-10-07
- **Actor:** Agent 04
- **Trigger:** `docs/COORDINATION.md` "Commit identity (P-07-2)" and `docs/receipts/2026-10-07-provenance-correction-commit-authorship.md` (Agent 01).

**FACT (checked at the time of writing):**
- `git config user.name` read `Agent 07 Marketing <michaelos+agent-07-marketing@users.noreply.github.com>` in this worktree. That value lives in the shared `.git/config`, which each agent launch overwrites.
- All commits on this branch since its base are recorded with the author `Agent 07 Marketing`. That is **wrong**.
- **Evidence they are Agent 04's work:**
  - each was made in `/home/michaelos/business-os-worktrees/agent-04-state` and pushed only to `research/agent-04-state`, which only Agent 04 writes
  - every commit subject is an Agent 04 subject
  - Agent 07's own work is on `research/agent-07-marketing`

## Corrected authorship: all authored by **Agent 04 (State)**, not "Agent 07 Marketing"
| Commit | Subject |
|---|---|
| `be6aed9` | complete agent 04 round-one research: durable state architecture |
| `a7b9b06` | agent 04: round two start — status WORKING (lane D state spine) |
| `3af8e92` | agent 04: round two — Postgres state spine, receipts, verify_chain (lane D wave one) |
| `7f0649a` | agent 04: claim R1 task (migration 0005, R3 hash, DBOS role) — status WORKING |
| `a0d1fbe` | agent 04: D-01 migration 0005 (R1 tables, R5 PANIC, R8) + D-02 ADR-0010 ledger (MBOS-RH-1) |
| `2b8fe3d` | agent 04: Done D-01, D-02 @ a0d1fbe; DBOS answers; claim D-03 |
| `ca59e3c` | agent 04: D-03 reporting views documented + tested; D1 fresh-cluster restore drill (179 receipts, ADR-0010 reference verifies) |
| `908397f` | agent 04: Done D-03 @ ca59e3c; claim D-05 (R12) |
| `797a4e5` | agent 04: D-05 migration 0006 — R12 strict item edges (equals 01 ITEM_TRANSITIONS, 41 edges) |
| `bd64f72` | agent 04: Done D-05 @ 797a4e5; re-open + claim D-04 (gaps vs 05 requirements) |
| `14bd690` | agent 04: D-04 migration 0007 — Lane E requirements (PANIC panic_set/views/bootstrap FROZEN, execution claims, gateway edges, bucket multi-cap budget) |
| `4bbd6a6` | agent 04: Done D-04 @ 14bd690 |
| `cc989ce` | agent 04: WAITING — no READY lane-D task; proposed D-06..D-10 |
| `e10e6fe` | agent 04: claim D-06 (State MCP server) |
| `012c141` | agent 04: D-06 State MCP server — only agent write path (identity/scope in provenance, mcp_calls audit, every write receipted) |
| `75c7fc9` | agent 04: Done D-06 @ 012c141; claim D-07 |
| `215a861` | agent 04: D-07 filesystem artifact store (content-addressed, atomic, tamper-detecting, backup/restore aware) |
| `0889de6` | agent 04: Done D-07 @ 215a861; claim D-08 |
| `d668386` | agent 04: D-08 pgvector rebuildable index (D3: drop/rebuild -> identical results; HNSW proven) |
| `c733f92` | agent 04: Done D-08 @ d668386; claim D-10; propose D-11 (05 velocity count), D-12 |
| `6533334` | agent 04: D-10 migration 0011 — 06's consent/DNC ledger under lane D (same-tx receipts, fail-safe asymmetry, PII column grants) |
| `dcde281` | agent 04: D-10 DDL delivered; acceptance blocked on A-01 phase 2; WAITING |
| `7ef19ba` | agent 04: claim D-13 (review 01 lane-D backend @ 8c3e4fd) |
| `ffb9e24` | agent 04: D-13 review of 01's lane-D backend — e2e timeout root-caused (helper 'body' column + runner hang); MODIFY FK bug fixed lane-side (0012) |
| `5cfeda4` | agent 04: Done D-13 @ ffb9e24; claim D-11 |
| `341c5d2` | agent 04: D-11 caps.velocity_actions_per_hour (0013) — action-count velocity under the shared budget lock |
| `9915d5c` | agent 04: Done D-11 @ 341c5d2; claim D-14 |
| `80bb135` | agent 04: D-14 update_item_doc keeps scorecard/recommendation entity on receipts (0014) |
| `02f76a1` | agent 04: Done D-14 @ 80bb135; claim D-15 |
| `a08dd9f` | agent 04: D-15 provision helper — workers/tests run as real mbos_dbos login; bootstrap.sh uses it |
| `3a1b004` | agent 04: D-16 card enrichment inputs — append_item_research (fixes lost-update), v_item_card_inputs, docs |
| `92d52b1` | agent 04: Done D-16 @ 3a1b004; WAITING (no READY lane-D task) |
| `e5fdb6b` | agent 04: claim D-17 (operator-note store) |
| `77d1f17` | agent 04: D-17 operator-note store (0016) — append-only, human-only, receipted; folded document passes Agent 03's note check |
| `466e735` | agent 04: Done D-17 @ 77d1f17; WAITING |
| `3cd301d` | agent 04: record Agent 03's acceptance of D-17 |
| `0bc1446` | agent 04: read-through of 01's spine_d @ f4c6529 — enrichment A,B,A bug (reproduced), unused D-14 entity, 3 low notes |
| `c97ba6b` | agent 04: propose D-18 (attach_card_block) in status |

(`be6aed9` is the round-one research commit. The rest are round two.)

## Remedy
- **From this commit on**, every commit on this branch sets its identity explicitly:
  `git -c user.name='Agent 04 State' -c user.email='michaelos+agent-04-state@users.noreply.github.com' commit …`
  and I check `git log -1 --format='%an'` before pushing.
- Pushed history is **not** rewritten, so this receipt is the correction of record.
- The root cause is operator-side and unchanged by me: `git config extensions.worktreeConfig true` in `~/bin/mbos-agent`, then a per-worktree identity.
