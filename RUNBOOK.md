# RUNBOOK: Michael Business OS spine (round two, DRY-RUN)

Owner: Agent 01 (Lane A, Core Platform and integration). Branch: `research/agent-01-coordinator`.

**Core law:** no action without a receipt, and no receipt without provenance.

**Everything here is DRY-RUN.** No code path in this branch contacts sellers or customers, spends money, publishes, or makes an external network call:
- The only effector is `DryRunEffector`.
- The database refuses any effector receipt or effector call with `dry_run != true` (constraints `mvp_dry_run_only` and `effector_mvp_dry_run_only`).

---

## 1. What this is

```
SourceAdapter.fetch ─► Normalizer ─► ingest (dedup) ─► Scorer ─► record_score ─► route
   (lane B)            (lane B)      Item DISCOVERED   (lane C)   SCORED →         PASS → ARCHIVED
                                     → NORMALIZED                 RECOMMENDED      MAYBE → RESEARCHING
                                                                                   YES → ActionRequest (tier 0)
                                                                                         → AWAITING_APPROVAL
      Michael: mbos decide … YES | NO | MODIFY | HOLD   (Operator UI, lane F, replaces the CLI)
                                                                                         │
            APPROVED → ACTING ─► Gateway (8 guard checks, lane E) ─► DryRunEffector ─► ACTED
                                                                     + ACTION_EXECUTED receipt
```

Each arrow above is a DBOS step or a datasource transaction:
- Every database effect, its receipt(s) and its outbox row commit in **one** transaction.
- Workflows survive crashes and restarts. On launch, DBOS recovers every PENDING workflow from the system database.

| Piece | Where |
|---|---|
| Frozen contracts (single source of truth) | `docs/research/contracts/` (v1.0.0, ADR-0004) |
| Pydantic models aligned to them | `src/mbos/contracts/models.py` |
| Postgres spine DDL | `src/mbos/db/migrations/0001_spine.sql` (schema `mbos`) |
| Ledger primitives (provenance, receipts, same-transaction transitions) | `src/mbos/ledger.py` |
| Spine operations (ingest, score, route, decide, act, outcome, kill switch) | `src/mbos/spine.py` |
| DBOS workflows | `src/mbos/workflows.py` |
| Lane interfaces | `src/mbos/interfaces.py` |
| Reference stubs for other lanes | `src/mbos/reference/` |
| Operator CLI | `src/mbos/cli.py` (`mbos …`) |
| Acceptance suite A1–A10 | `tests/acceptance/` |

## 2. One-time setup (project-local, no sudo)

The EliteDesk has no Podman and only system Python 3.10. Everything below installs inside the worktree.

```bash
cd /home/michaelos/business-os-worktrees/agent-01-coordinator
python3 -m venv /tmp/uvboot && /tmp/uvboot/bin/pip install uv && mkdir -p .tools && cp /tmp/uvboot/bin/uv .tools/uv
export UV_PYTHON_INSTALL_DIR=$PWD/.tools/python UV_CACHE_DIR=$PWD/.tools/uv-cache
.tools/uv python install 3.12
.tools/uv venv --python 3.12 .venv
.tools/uv pip install --python .venv/bin/python -e ".[dev]"
```

`.venv/`, `.tools/` and `.pgdata/` are git-ignored.

**Non-editable install.** `pip install .` (or a wheel) works with no environment variables: `setup.py` copies the frozen
contracts and `config/operator_profile.v1.json` into `mbos/_data/` at build time from their single source files. A
missing operator profile raises rather than guessing Michael's capabilities (`MBOS_OPERATOR_PROFILE` overrides).

**Opportunity card.** `mbos card ITEM_ID` prints Michael's decision-ready card (ADR-0011); the Operator UI renders the same
card at `/item/<id>`.

## 3. Database

**Development and tests.** `pgserver` runs a real PostgreSQL 16.2 from a pip wheel, project-local, with no system install:

```bash
eval "$(.venv/bin/mbos devdb up)"    # starts Postgres in ./.pgdata, creates mbos_app + mbos_sys, exports the URLs
.venv/bin/mbos migrate               # forward-only; refuses if an applied migration was edited
.venv/bin/mbos devdb down            # stop
```

**Production target (ADR-0001).** PostgreSQL 16 under Podman and Quadlet/systemd. It uses the same SQL. Set the two variables and run `mbos migrate`:

```bash
export MBOS_DATABASE_URL=postgresql://mbos@/mbos_app?host=/run/postgresql
export MBOS_SYSTEM_DATABASE_URL=postgresql://mbos@/mbos_sys?host=/run/postgresql
```

Rules:
- `MBOS_DATABASE_URL` holds the business state (`mbos` schema) and DBOS transaction checkpoints.
- `MBOS_SYSTEM_DATABASE_URL` holds DBOS workflow state. Keep it separate.
- Receipts may only be written under READ COMMITTED. The chain trigger raises otherwise, because a snapshot-isolated writer could fork the chain.

## 4. Daily operation

```bash
eval "$(.venv/bin/mbos devdb up)"
.venv/bin/mbos worker --fixture fixtures/sources/illustrative.json   # long-running; Ctrl-C to stop
.venv/bin/mbos queue                       # what needs Michael (opportunity cards + payload hash)
.venv/bin/mbos decide <areq> YES --seen <first 12 hex of payload hash> --step-up   # --step-up: irreversible/money-like
.venv/bin/mbos decide <areq> NO  --seen <hash> --reason "too far this week"
.venv/bin/mbos decide <areq> MODIFY --seen <hash> --change "summary=Offer \$725 cash, pickup Saturday"
.venv/bin/mbos decide <areq> HOLD --seen <hash> --hold-until 2026-10-09T15:00:00Z --renotify PT24H
.venv/bin/mbos ping <item_id>              # wake a HOLD whose wake_on includes michael_ping
.venv/bin/mbos show <item_id>              # item + its receipt trail
.venv/bin/mbos outcome <item_id> flip_sold --revenue 2100 --cost 1325 --hours 10
.venv/bin/mbos audit                       # chain + provenance + dry-run + contract conformance; exit 1 on failure
```

How decisions and workers interact:
- `--seen` is required. A decision on a payload Michael did not see is refused, both by the CLI and by a database trigger.
- `decide` works with **no worker running**. The decision row is the truth, and the DBOS message is only a wake-up. The next `mbos worker` start recovers the parked workflow, which finds the decision on its first poll.
- Stopping the worker is always safe. Parked workflows stay PENDING and resume on the next start. The worker deliberately exits hard, because DBOS threads parked at the approval gate are non-daemon.

**Approval semantics** (contract `approval.schema.json`):
- **YES:** executes the frozen payload exactly. The gateway recomputes the payload hash and checks it equals both the request's hash and the hash Michael saw.
- **NO:** requires a reason. The item goes to REJECTED and then ARCHIVED.
- **MODIFY:** creates a new ActionRequest with `derived_from`. The old one is closed as `rejected`, with an intent naming its successor, and cannot be approved any more.
- **HOLD:** a durable wait with no compute.
  - It re-notifies after `renotify_after` (an APPROVAL_REQUESTED receipt).
  - It wakes on `hold_until`, `escalate_after` or `michael_ping`, and is re-presented as AWAITING_APPROVAL.
  - It **never executes on its own.**

## 5. Kill switch (PANIC). Lane E owns the full semantics.

```bash
.venv/bin/mbos panic on  --reason "something looks wrong"                                   # L3 global
.venv/bin/mbos panic on  --key capability_freeze:comms.email.send --reason "template issue"  # L2
.venv/bin/mbos panic off --reason "cleared"
```

Each change writes a `KILL_SWITCH_CHANGED` receipt.

The gateway **fails closed**. If the flag is missing, malformed, unreadable or set, every action is refused. It records an `ACTION_FAILED` receipt, sets the request to `cancelled_by_freeze` and moves the item to FAILED.

Not yet built (lane E): egress cut, credential lease revocation, LiteLLM budget zeroing and cancelling unstarted workflows (B29).

## 6. Tests

```bash
.venv/bin/python -m pytest -q                       # everything (about 80 s; starts its own throwaway Postgres)
.venv/bin/python -m pytest -q -m acceptance         # A1–A10 only
.venv/bin/python -I docs/research/contracts/validate_contracts.py docs/research/contracts   # frozen-contract check
```

| Test | What proves it | File |
|---|---|---|
| A1 | Injected fault between the UPDATE and the receipt leaves neither; a DB-side receipt failure rolls back the state change | `test_a01_atomic_transition.py` |
| A2 | UPDATE/DELETE/TRUNCATE are refused on 7 ledgers, both as `agent_write` (which holds the grants) and as superuser | `test_a02_insert_only.py` |
| A3 | `verify_chain` passes. A one-byte tamper and a deleted row are each detected. 8 concurrent writers keep one gap-free chain. A snapshot-isolation writer is refused | `test_a03_verify_chain.py` |
| A4 | Every receipt's provenance resolves and satisfies the anyOf rule. Empty or dangling provenance is refused in Python and in the DB | `test_a04_provenance.py` |
| A5 | A real `os._exit` mid-ACT (before and after the effector commits), then a restart in a new process: exactly one effector call and one ACTION_EXECUTED | `test_a05_crash_resume.py` |
| A6 | YES runs the frozen payload. NO needs a reason. MODIFY creates a `derived_from` request and the old one is dead. HOLD re-notifies, wakes on time, never executes, survives a hard process restart and wakes on ping | `test_a06_decisions.py` |
| A7 | The audit finds zero dry-run exceptions. The DB refuses live effector receipts and calls. The gateway refuses when dry-run mode is off | `test_a07_dry_run_only.py` |
| A8 | A per-agent daily LLM cap blocks once exceeded. The default cap is $0. Agents cannot delete their spend | `test_a08_llm_cap.py` |
| A9 | Missing, malformed, unreadable or set flag means the gateway denies. L2 capability freeze works. End to end: PANIC, then YES, gives FAILED, `cancelled_by_freeze` and no effector call | `test_a09_panic.py` |
| A10 | Every stored record in the shared runtime DB and the seeded DB validates against the frozen contracts | `test_a10_conformance.py` |

**Known scope limits.** These are honest gaps, tracked in `docs/integration/ROUND_TWO_INTEGRATION.md`:
- **A8-LITELLM.** The cap is enforced by the spine's ledger, not yet by LiteLLM virtual keys (lane E).
- **A9.** Only the gateway part of L3 is built. Egress cut and lease revocation are lane E.
- **Scoring:** the default `Scorer` is a PLACEHOLDER, not economic advice.
  - Agent 03's real engine plugs in via `mbos.adapters.economics.EconomicsEngineScorer(config_dir=...)`.
  - Install it from 03's branch as a clean archive. Remove any committed `build/` tree first: setuptools can otherwise package a stale `build/lib`, and the label will not match the code.
    ```bash
    H=$(git rev-parse --short origin/research/agent-03-economics); D=$(mktemp -d)
    git archive $H economics | tar -x -C $D && rm -rf $D/economics/build
    .tools/uv pip install --python .venv/bin/python --reinstall-package mbos-economics $D/economics
    .venv/bin/python -c "import mbos_economics as m; print(m.__version__)"   # must match 03's __init__.py at $H
    ```
  - `tests/integration/test_lane_c_economics.py` exercises it and skips if the package is not installed.
- **The state store is the reference DDL** until the port onto Agent 04's schema (integration ruling R1).

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `MBOS_DATABASE_URL and MBOS_SYSTEM_DATABASE_URL must be set` | Run `eval "$(.venv/bin/mbos devdb up)"`, or export the production URLs |
| `migration … was edited after being applied` | Never edit an applied migration. Add `0002_*.sql` |
| `receipts must be written under READ COMMITTED` | A caller opened REPEATABLE READ/SERIALIZABLE. Use `mbos.runtime.tx` or `engine.begin()` |
| `illegal item transition X -> Y` | The state machine (ADR-0004) forbids it. See `src/mbos/state_machine.py` (mirrored in the DB) |
| `approval void — payload_hash_seen …` | The payload changed or the wrong hash was supplied. Re-read `mbos queue` |
| `mbos audit` reports `chain.ok=false` | Tampering, or a bypass of the triggers. `first_bad_seq` is the first broken row. Treat it as an incident: run `panic on`, then restore from backup (lane D) |
| Item stuck in AWAITING_APPROVAL after `decide` | No worker is running. Start `mbos worker`; it recovers and proceeds |
| `pgserver` socket errors after a reboot | `mbos devdb up` again. Dev Postgres is not a systemd service; production uses Quadlet |

## 8. Safety checklist before ANY change to this branch

- Is there still no code path to a live effector? `grep -rn "dry_run" src/` should show only `True` and guard checks.
- Do `mbos audit` and `pytest -q` both pass?
- Were the frozen contracts left untouched? A contract change needs an ADR, a semver bump and an Agent 01 sign-off.


## Foreman check (idle agents)
`.venv/bin/python -I tools/foreman.py --wake-text` fetches origin, prints each lane's state/claim/next READY tasks and exits 2 if an agent is idle while READY work exists for it. Read-only; it cannot start sessions. Schedule it on the host (OWNER_ACTIONS D2).


## Bounded workers and usage telemetry
See `docs/runbooks/AGENT_RUNTIME.md` (launcher `tools/worker.py`, router `config/model_router.v1.json`, telemetry `var/telemetry/worker_runs.jsonl`).
