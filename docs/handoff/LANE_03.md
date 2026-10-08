# Lane 03 handoff (Economics / Scoring, build lane C)
Tags: FACT / INFERENCE / UNKNOWN. Everything is DRY-RUN.

- **Branch / head (pushed):** `research/agent-03-economics`, head recorded in the closeout reply (see AGENT_STATUS `Done:`). Package `mbos_economics` **0.13.0**; scoring config **2026.10.2**; estimation priors 2026.10.4; mission planner config 2026.10.1.
- **Role and boundaries:** deterministic, replayable economics and scoring for flips AND services: gates first, then score; YES/MAYBE/PASS; `inputs_hash`, `scorecard_id`; no LLM arithmetic; no clock or random inside the engine. Never touches other agents' branches, never merges to main, never spends or contacts anyone. Owner policy values (cash, $/h, class thresholds) are CONFIG and are coordinator defaults, not Michael-confirmed.
- **Completed:** C-01..C-21 and X-03 (commits in AGENT_STATUS `Done:`). Latest: C-19 class-aware gates (no universal profit floor, ADR-0012), C-20 digest by capital-velocity rank, C-21 `plan_week`. Receipts: `docs/receipts/2026-10-0{7,8}-*.md`.
- **Outstanding:** C-22 Valuator (not started), plus P-03-10..13 in AGENT_STATUS `Proposed tasks`, each with acceptance.
- **Blockers:** owner: MICHAEL_DECISIONS #1 (cash), #2 ($/h), #6 (quote rate), #9 (deal classes, cash context). Dependency: P-03-13 needs D-18 (capital ledger).
- **Key files** (under `economics/`):
  - `src/mbos_economics/engine.py`: `compute`, `score_item`, `_deal_class`, `_ranking`, walk-away price.
  - `lanes.py`, `inputs.py`: lane arithmetic and strict input validation.
  - `config/scoring-config.json`: all constants (every change = version bump plus a copy in `config/history/`).
  - `mission.py`, `digest.py`, `estimate.py`, `comps_feed.py`, `enrich.py`, `valueadd.py`, `learn.py`, `replay.py`, `replay_audit.py`, `canonical.py`.
  - `tests/` (~350 tests), `examples/*.scored.json` (14 goldens), `examples/class_aware/` (TV, mower, Recon), `examples/deal_sniffer/`, `scripts/regen_*.py`, `scripts/lane_d_export.py`.
- **Run commands:**
  - Setup: python 3.10+ with `pytest jsonschema`; add `psycopg[binary] pgserver sqlalchemy` for the lane-D tests.
  - Tests: `cd economics && PYTHONPATH=src:tests python -m pytest tests -q` → expect ~332 passed, 21 skipped.
  - Full (env): also set `MBOS_CONTRACTS_DIR=<agent-01 archive>/docs/research/contracts`, `PYTHONPATH=…:<agent-01 archive>/src`, and `MBOS_LANE_D_STATE_DIR=<agent-04 archive>/state` → expect 353 passed.
  - Health proof: the same pytest command; goldens replay byte-for-byte.
  - Score from a CLI: `python -m mbos_economics score|replay|estimate|digest|audit|note`.
- **Regenerate on EVERY engine version bump or config change** (ids are seeded by the engine version):
  1. `scripts/regen_examples.py`, `scripts/regen_deal_sniffer.py`, `scripts/regen_class_examples.py`.
  2. `scripts/lane_d_export.py --state-dir <agent-04 archive>/state --out tests/fixtures/lane_d_export/export.json`.
  3. Update `docs/research/agent-03-sensitivity-michael-decisions.md` header (version, config hash) via `scripts/sensitivity_report.py` (tables only; the findings text is hand-written).
  4. Re-pin `tests/test_adr0010.py` hash prefixes and `scoring_config_version` literals.
- **Interfaces:**
  - Consumes: Item v1 and frozen contracts (pinned copies in `tests/contracts/`, re-vendor with `git show origin/research/agent-01-coordinator:<path>`; `operator_profile.v1.json` @ 24c4d3d); Agent 02 listings and comps fixtures; Agent 04 `mbos_state.StateStore`, `mbos.v_item_documents`, `operator_notes` (migration 0016).
  - Provides: Item `scores` + `recommendation` + provenance + receipt drafts, `economics` / `logistics` / `seasonality` / `why` / `value_add` blocks via Agent 01 `spine.record_enrichment`, digest rows, `mission_plan`, the replay audit.
- **Known pitfalls:**
  - Any config value change without a version bump is caught by the audit (by design).
  - Commit identity: the shared `.git/config` was Agent 07's; early commits on this branch carry `Agent 07 Marketing` as author. Use `git -c user.name='Agent 03 Economics' -c user.email='michaelos+agent-03-economics@users.noreply.github.com' commit` per `docs/COORDINATION.md`. History was not rewritten.
  - Never `git add -A` after building a wheel: `economics/build/` is ignored and guarded by a test.
  - Money must be int/float/Decimal, not strings. Notes with numeric-only model tokens are refused by `load_kb`.
  - Agent 01's card composes and caps its own `why` list; do not assert lane-C reason order on the card.
  - A service with materials cash cannot be `DO_NOT_SPEND` (A-23 validator); it is `DEPLOY` with "Services only" in the explanation.
  - Services have no cash multiple (null); their velocity sits at the cap, so rank within lane.
- **Open questions (UNKNOWN):** Michael's real cash, hours, weekly target and class thresholds (owner); seasonality sources need a human read (only the concrete-saw entry is owner-stated); whether services and flips should share one rank scale (Agent 01 ruled: do not interleave in the ranked list, mix in the planner).
