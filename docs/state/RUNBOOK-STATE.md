# RUNBOOK — MBOS state spine (Postgres)

Owner: Agent 04 (lane D). Host: `caoscare1-hp-elitedesk` (Ubuntu 22.04, 8 cores, 14 GiB RAM). Date: 2026-10-07.
Tags: **FACT** (observed on this host or in a test run), **INFERENCE**, **RECOMMENDATION**, **UNKNOWN**.

## 0. Isolation rules

- The MBOS cluster is its own cluster: its own data dir (`~/.local/share/mbos/pg16`), port **55432**,
  socket dir and roles. It never uses port 5432 or a system cluster, and it never touches CAOSCare.
  **FACT:** on 2026-10-07 nothing was listening on 5432 or 55432.
- Secrets live in `~/.config/mbos/secrets/` (dir 0700, files 0600) and `~/.config/mbos/pgpass` (0600).
  They are never committed.

## 1. Runtime choice for wave one

| | Wave one (now) | Target |
|---|---|---|
| Postgres | 16.2 binaries from the `pgserver` wheel in `state/.venv` (pgvector bundled) | `pgvector/pgvector:pg16` via Podman Quadlet (`state/bootstrap/podman/`) or PGDG `postgresql-16` |
| Supervisor | systemd **user** unit `mbos-postgres.service` | Quadlet-generated user unit |
| Why | **FACT:** Podman is not installed; this agent has no mandate to install system packages | Integration plan §1 runtime |

`pg-local.sh` looks for binaries in this order: `$PG_BIN`, then `/usr/lib/postgresql/16/bin`, then the
venv wheel. Moving to PGDG or Quadlet changes only where the binaries come from. The schema, roles,
scripts and tests stay the same.

## 2. First-time bootstrap

```bash
cd ~/mbos/state                          # durable checkout, NOT an agent worktree
python3 -m venv .venv && .venv/bin/pip install "psycopg[binary]>=3.1" pgserver
./bootstrap/pg-local.sh init             # initdb: checksums, UTF8, scram, loopback only
./bootstrap/pg-local.sh start
./bootstrap/bootstrap.sh                 # roles, DBs (mbos, mbos_dbos), passwords, migrations, verify_chain
```

`bootstrap.sh` is idempotent. **FACT:** a second run printed `schema up to date` and `verify_chain OK`.
Every migration is itself receipted (`CONFIG_VERSION_BUMPED`, provenance = `mbos_state.migrate` +
file sha256). The genesis receipt (seq 1) is migration 0001.

## 3. Startup and reboot plan

**Goal (D2):** after a power loss or reboot everything comes back with no manual steps, and the ledger is
proven intact before any agent writes.

1. **Boot.** systemd starts the user manager. This requires lingering (`Linger=no` today, **FACT**). One-time operator step:
   `sudo loginctl enable-linger michaelos`
   *Not executed by Agent 04: it is a host-level change outside this lane.*
2. **`mbos-postgres.service`** (Type=simple, `Restart=on-failure`) runs
   `pg-local.sh start-foreground`. Postgres crash recovery replays the WAL (`fsync=on`,
   `synchronous_commit=on`, `full_page_writes=on`), so every committed receipt survives.
3. **`mbos-chain-check.timer`** fires 5 minutes after boot and then hourly:
   - `verify-chain --anchor <last anchor>` runs first. A failure leaves the unit failed, and that is the
     alert hook.
   - On success it appends a new anchor.
4. **The DBOS app** (Agent 01) is ordered `After=mbos-postgres.service` and resumes its own workflows
   from `mbos_dbos`. Interrupted steps resume via DBOS. The state spine holds no workflow positions.
5. **Fail-closed.**
   - If Postgres is down, every write path is down too: there is no secondary store to drift into.
   - If `verify_chain` fails, the RECOMMENDATION is that 05's guard treats it as an L3 PANIC input (deny
     all effectors) until a human inspects.

Install (operator, once a durable checkout exists at `~/mbos`):
```bash
mkdir -p ~/.config/systemd/user
cp state/bootstrap/systemd/*.service state/bootstrap/systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mbos-postgres.service mbos-chain-check.timer
```

**Evidence (FACT, crash drill 2026-10-07 on a scratch cluster):**
- **Setup.** 206 receipts were committed. One more transition (state change and receipt) was left
  in flight and uncommitted.
- **Crash.** The postmaster got `SIGKILL`. `pg_ctl start` then ran crash recovery (`end-of-recovery checkpoint`).
- **Result:**
  - `verify_chain`: OK, 206 receipts.
  - The in-flight transition is absent: the item state is unchanged and no receipt exists (both-or-neither).
  - Receipts equal outbox rows.

## 4. Routine verification

| Check | Command | Expected |
|---|---|---|
| Chain integrity | `MBOS_DSN=... python -m mbos_state verify-chain --anchor <log>` | `OK: N receipts checked` |
| Head | `python -m mbos_state head` | JSON with seq / row_hash |
| A7 dry-run audit | `SELECT count(*) FROM mbos.v_a7_live_effects` | `0`. The `receipts_wave1_dry_run_only` CHECK also blocks live effects |
| Outbox backlog | `SELECT count(*) FROM mbos.outbox WHERE dispatched_at IS NULL` | small, draining |
| HOLD backlog | `SELECT * FROM mbos.v_hold_backlog` | reviewed daily |

## 5. Backups and restore (D1)

- **Nightly** (`bootstrap/backup-dump.sh`):
  - a `pg_dump -Fc`
  - an offline-verifiable chain export (`chain-<ts>.jsonl`)
  - an anchor append
  - an offline verification of the export
  - `SHA256SUMS`

  Copy `~/.local/share/mbos/backups/` and the anchor log **off-box**.
- **Drill, same cluster** (`bootstrap/restore-drill.sh <dump>`): restores into a scratch DB, runs `verify_chain` against the anchor, then drops the scratch DB.
- **Drill D1, fresh cluster** (`bootstrap/restore-drill.sh --fresh-cluster <dump>`):
  1. `initdb` a brand-new cluster with its own port and socket.
  2. Bootstrap the roles from scratch.
  3. `pg_restore` the dump.
  4. Run `verify_chain` against the anchor, as `mbos_reader`.
  5. Export the chain and verify it offline.
  6. Verify it again with the **ADR-0010 reference** `mbos_canonical.verify_chain`.
  7. Tear the cluster down.

  **FACT (2026-10-07):** the drill passed on a 179-receipt seeded dry-run history (`bootstrap/seed_demo.py`): flip and service lanes, HOLD and YES, dry-run effector calls, outcomes, PANIC. The reference result was `(True, '179 receipts verified')`.
  - *Caveat:* the "fresh host" was a fresh cluster on the same machine. The procedure is identical on a second machine (copy the dump and the anchor log over first).
- **Artifacts (D-07):**
  - Files live under `$MBOS_ARTIFACT_ROOT` (default `~/.local/share/mbos/artifacts`), indexed in `mbos.artifacts`.
  - `backup-dump.sh` copies them to `artifacts-<ts>/` and verifies the copy against the index.
  - The fresh-cluster drill re-verifies them against the *restored* index (set `MBOS_DRILL_ARTIFACTS=<backup>/artifacts-<ts>`).
  - Routine check: `python -m mbos_state verify-artifacts`. It re-hashes every file and reports missing, modified and unindexed files.
  - **FACT (2026-10-07):** the drill passed with 5 fs + 1 inline artifacts and 183 receipts.
- **PITR:** `wal_level=replica` is already set. pgBackRest (`archive_command`, a repo on off-box storage)
  lands once an off-box target exists. **UNKNOWN:** the target (NAS, USB or cloud).

## 6. Tamper response

`verify_chain` reports `first_bad_seq` and one of these reasons:

| Reason | Meaning |
|---|---|
| `seq gap` | rows were deleted |
| `prev_hash does not match` | rows were rewritten or reordered |
| `row_hash does not match canonical bytes` | the hashed bytes were edited |
| `stored columns differ from hashed canonical document` | a column was edited |
| `anchored receipt is missing` | the tail was truncated |
| `row_hash differs from external anchor` | the whole tail was rewritten |

Response:
1. Freeze effectors (05 L3).
2. Restore the last good dump into a scratch DB.
3. Diff it against the live DB from `first_bad_seq`.
4. Keep both copies as evidence.

Superuser access to the cluster is the trust boundary. The anchors and the off-box exports are what make a
superuser rewrite detectable.

## 7. Recovery objectives (proposal; Michael decides, see MICHAEL_DECISIONS "eventually")

- **RECOMMENDATION:** RPO 15 min and RTO 4 h, matching the coordinator default. That needs pgBackRest WAL
  archiving off-box.
- **Until that lands, the real RPO is 24 h** (nightly dump) for host loss, and 0 for a process or OS crash
  (WAL, FACT per the drill above).
