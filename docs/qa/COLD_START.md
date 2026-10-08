# Cold-start acceptance (G-15)

Date 2026-10-07. Fresh worker, no prior context. Coordinator head `d79bd27` (`origin/research/agent-01-coordinator`). DRY-RUN only. Docs followed: START_HERE.md, RUNBOOK.md sections 2-4, docs/runbooks/AGENT_RUNTIME.md, LANE_06 handoff (UI).
Host: EliteDesk, system Python 3.10.12, no psql, no Podman.

**Verdict: PASS with 2 code/doc gaps (F-70, F-71) and 4 doc notes below.** Every step ran unaided once the notes were applied. Env vars from `devdb up` do not persist between separate shell invocations: re-run the `eval` in each one.

## Steps (run in order; `$W` = your new worktree)
| # | Command | Expected output | Result |
|---|---|---|---|
| 1 | `git fetch -q origin && git worktree add --detach $W origin/research/agent-01-coordinator && cd $W` | `HEAD is now at <sha>`; dir has `src fixtures docs RUNBOOK.md` | PASS (use any fresh path; RUNBOOK's `agent-01-coordinator` path is the coordinator's own tree, see N1) |
| 2 | `python3 -m venv /tmp/uvboot && /tmp/uvboot/bin/pip install uv && mkdir -p .tools && cp /tmp/uvboot/bin/uv .tools/uv` | uv copied | PASS |
| 3 | `export UV_PYTHON_INSTALL_DIR=$PWD/.tools/python UV_CACHE_DIR=$PWD/.tools/uv-cache; .tools/uv python install 3.12; .tools/uv venv --python 3.12 .venv` | Python 3.12 installed, `.venv` created | PASS (warning "Executable already exists at ~/.local/bin/python3.12 ... use --force" is harmless, N2) |
| 4 | `.tools/uv pip install --python .venv/bin/python -e ".[dev]"` | ends with `+ websockets==...`; `.venv/bin/mbos` exists | PASS |
| 5 | `eval "$(.venv/bin/mbos devdb up)"` | no output, rc 0; `MBOS_DATABASE_URL` and `MBOS_SYSTEM_DATABASE_URL` exported (socket under `$W/.pgdata`) | PASS |
| 6 | `.venv/bin/mbos migrate` | `applied: ['0001_spine.sql', ... '0005_gapless_receipt_seq.sql']` | PASS |
| 7 | `.venv/bin/mbos worker --fixture fixtures/sources/illustrative.json --once` | JSON listing items `created: true`; exits rc 0 (without `--once` it runs until Ctrl-C and prints nothing, N3) | PASS |
| 8 | `.venv/bin/mbos queue` | two `[PENDING_APPROVAL]` entries (trailer flip, doorbell service) each with an `areq_...`, payload sha256 and a `decide:` line | PASS (no `item_id` shown: F-70) |
| 9 | Get an item id: copy `item_id` from step 7 output (e.g. `itm_01M4...`) | an `itm_...` string | PASS via workaround; FAIL as documented: **F-70** |
| 10 | `.venv/bin/mbos card <item_id>` | text card: title, `Conway, AR - $950`, WHY, ESTIMATED NUMBERS, CAPITAL, status timeline, UNKNOWN fields shown as UNKNOWN | PASS |
| 11 | `.venv/bin/mbos card <item_id> --json` / `mbos show <item_id>` | JSON with `card_version: "1.0.0"` / item + receipt trail | PASS |
| 12 | `.venv/bin/mbos decide <areq> NO --seen <12 hex from queue> --reason "..."` | JSON with `"reason"`, `new_action_request_id: null`, rc 0 | PASS |
| 13 | `.venv/bin/mbos audit` | all sections `"ok": true`, `"failures": []`, rc 0 | PASS |
| 14 | Operator UI (not in coordinator head): `D=$(mktemp -d); git archive origin/research/agent-06-communications operator_ui comms_spec \| tar -x -C $D`; with step 5 env and `MBOS_OPERATOR_PIN=<pin>`: `PYTHONPATH=$D .venv/bin/python -u -m operator_ui serve --port 8765` (`-u` or a log file is needed to see the banner) | `Operator UI on http://127.0.0.1:8765/ (dry-run ...)`; `GET /` 200; `GET /item/<item_id>` 200 and contains the item title | PASS via LANE_06 handoff recipe; FAIL as documented in RUNBOOK: **F-71** |
| 15 | `.venv/bin/mbos devdb down` | `dev postgres stopped` | PASS |

## Notes (doc-only, applied here)
- N1: RUNBOOK section 2 starts with `cd .../agent-01-coordinator`. That is Agent 01's own tree; do not use it. Use your own worktree (step 1).
- N2: the uv "Failed to install executable" warning is benign.
- N3: `mbos worker` is long-running and silent; `--once` (undocumented in RUNBOOK) ingests the fixture, routes and exits. Needed for scripted runs.
- N4: shell state: `eval "$(mbos devdb up)"` must be repeated in every new shell/tool call; `devdb up` is idempotent. `psql` is not installed, so use `mbos` or Python/psycopg to inspect the DB. `curl`/`wget` may be denied for workers: probe the UI with `python -c 'urllib.request.urlopen(...)'`.

## Code gaps filed (for 01; in `qa/mbos_qa/__main__.py` FINDINGS)
- F-70: `mbos queue` shows no `item_id`, no command lists items, but `card`/`show`/`outcome` need one.
- F-71: RUNBOOK has no Operator UI start instructions and the UI is not on the coordinator head.

## Second-read check
A second reader can follow the table top to bottom using only this file plus the lane-06 branch; the only judgement call is step 9 (copy the id from step 7 output) until F-70 is fixed.
