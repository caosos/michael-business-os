# Receipt: Round-Two state spine implementation (lane D)

- Timestamp: 2026-10-07T16:37:46Z
- Agent: 04 (Postgres / State / Receipts)
- Branch: research/agent-04-state
- Host: caoscare1-hp-elitedesk (Ubuntu 22.04.5, Python 3.10.12)
- Related output: `state/`, `docs/research/agent-04-round-two.md`, `docs/state/RUNBOOK-STATE.md`

## Inputs read (provenance)
- `git fetch origin` at the start of the session.
- `origin/research/agent-01-coordinator` @ `acb6f3b`:
  - `docs/research/agent-01-integration.md`
  - ADR-0001, ADR-0002, ADR-0004, ADR-0008
  - `docs/research/contracts/*` (frozen v1.0.0), vendored verbatim into `state/tests/contracts-v1.0.0/`. The git blob ids are listed in its README and were re-checked with `git hash-object`.
- Own round-one material: `docs/research/agent-04-state.md`.

## Actions taken
- Wrote migrations 0001–0004, roles/bootstrap/backup/restore scripts, systemd and Quadlet units, the `mbos_state` Python package, and 93 tests.
- Created a Python venv at `state/.venv` (gitignored) containing psycopg 3.3.6, pytest 9.1.1, jsonschema 4.26.0 and pgserver 0.1.4. pgserver provides the PostgreSQL 16.2 binaries.
- Ran throwaway clusters only:
  - pytest: temp dir, port 55433
  - bootstrap, crash, backup and restore drills: scratchpad, port 55499, socket in `$XDG_RUNTIME_DIR`

  All of them were stopped.

## Not done (deliberately)
- No system packages installed and no `loginctl enable-linger`: both are host changes outside this lane.
- No persistent MBOS cluster at `~/.local/share/mbos`.
- No user units installed.
- Podman Quadlet units are written but **untested**, because Podman is absent.
- No contact with CAOSCare, external services or other agents' worktrees. Agent 01 has its own pgserver dev cluster running; it was observed and left alone.

## Results observed (FACT)
- `pytest`: 93 passed (PostgreSQL 16.2).
- `bootstrap.sh`:
  - run 1: 4 migrations applied, each with a CONFIG_VERSION_BUMPED receipt; `verify_chain` OK as `mbos_reader` over TCP with scram
  - run 2: `schema up to date`; OK
- Crash drill: 206 receipts committed, plus one uncommitted transition in flight. The postmaster was killed with SIGKILL and then restarted. Results:
  - `verify_chain` OK, 206 receipts
  - the in-flight state change and its receipt are both absent
  - receipts = outbox rows
- Backup and restore drill: pg_dump, chain export, anchor, and offline verify all OK. The restore into a scratch DB passed `verify_chain` against the anchor (206).

## Migration checksums
```
    588450717c495405113acd2290f4ed6c790ae05e738fc97e395fb3f1b28350eb  migrations/0001_foundation.sql
    5fa77b12a009d45a3b1710d68e327225734568da69e611394e4ac724fa997530  migrations/0002_domain.sql
    d3665074cc9ec2b0525af6972f6bcf936d9d2b3ac1302bbe760540bdc95d03e9  migrations/0003_api.sql
    360a15a3915f71aebc0477b499b5110a67cd3ab08da838c3c51429e1dd550605  migrations/0004_views_grants.sql
    dd62f0d494213e7f549545442bea05f0185a57d6a595e2001bdb7b1105b6db01  bootstrap/roles.sql
```
