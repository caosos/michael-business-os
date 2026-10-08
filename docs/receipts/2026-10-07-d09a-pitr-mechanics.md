# Receipt: D-09 part a (point-in-time-recovery mechanics, local target)

- Timestamp: 2026-10-08T00:34:56Z
- Agent: 04
- Why now: `docs/COORDINATION.md` (continuous execution): D-09's off-box destination needs a Michael decision (`docs/state/OWNER_QUESTION_BACKUPS.md`), but the mechanics do not, so that part proceeds in parallel.

## Built
- `state/bootstrap/archive-wal.sh`: PostgreSQL `archive_command`; durable, idempotent, and never overwrites a different file.
- `state/bootstrap/pitr-base-backup.sh`: a physical base backup verified with `pg_verifybackup`.
- `state/bootstrap/restore-pitr.sh`: restore to a named point, a timestamp, or latest, into a new directory.
- `pg-local.sh`: `MBOS_WAL_ARCHIVE` at init, and an `enable-archive` command for an existing cluster.
- `state/tests/test_pitr.py`: 7 tests run against a real archiving cluster.
- Runbook §5.

## Results (FACT)
- The PITR tests pass: 7 of 7, run twice. The full suite is 229 passed and 1 skipped (it needs Agent 03's loader).
- **Restore to a named point:**
  - 10 of 15 items come back, with the chain head equal to the recorded one, and `verify_chain` is OK.
  - The restored cluster accepts a new write, and the chain stays gapless.
- `--latest` gives 15 of 15.
- **Fail-closed:** an empty archive makes the restore fail and leaves nothing serving a shorter history.
- **Two real bugs found only by running it, both fixed:**
  1. **Restore aborted with "Permission denied".** `cp` preserved the read-only mode of archived WAL, so recovery could not use its own copy. `restore_command` now uses `cat … > %p`.
  2. **The wait loop checked the wrong database user.** It now uses the configured user, and stops waiting if the server dies.
- The tests leave nothing behind: nothing in `/run/user/1001` or in `/tmp` after a run.

## Not done (honest)
- **Part b is still blocked on Michael:** the off-box destination, and a restore drill from it.
- Encryption of off-box copies. They hold raw seller contact values.
- Automated retention and pruning of old base backups and WAL.
- pgBackRest is not installed, so this uses stock PostgreSQL tools.
- The **real** RPO is therefore still 24 h for host loss until a destination exists.
