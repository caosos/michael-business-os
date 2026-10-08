# Receipt: G-21a mission dry-run, stages 1-4

- Action: ran the real dev assembly (`tools/bootstrap_dev.py --ui-pin g21pin`, `mbos worker --fixture fixtures/sources/training_examples.json`, Operator UI on 8765) from a detached worktree of coordinator `63e24f8` in `/tmp/a07g21b/w`; drove the UI over HTTP (comp form x4, attest x2). DRY-RUN only: nothing sent, bought, published or contacted; `effector_receipts 0`; no other lane's branch touched; my dev Postgres, worker and UI were stopped afterwards. Processes from an earlier attempt (`/tmp/a07g21`, UI on 8766) were not mine to stop and were left running.
- Provenance: observed output of the commands recorded in `docs/qa/MISSION_DRYRUN.md`; lane pins 04 `6bdf941`, 05 `44a0fb2`, 06 `073a71c`, 03 `1262a85`, 02 `55a7e19`; read-only calls into `mbos_economics.comps_feed.research_step` and `mbos_discovery.comps.candidate_comps` for causes.
- Output: `docs/qa/MISSION_DRYRUN.md`. Stage 1 PASS, stage 2 PASS (audit conformance red), stage 3 FAIL, stage 4 FAIL. Findings F-102..F-110 (P0 F-106: the TV is blocked by `scope_override_required` and the UI has no form for it; the bootstrapped env diverges from A-41's stripped env).
- Health: `mbos_qa spine --rc` 105 passed / 0 failed (3 skipped); `mbos_qa card` 671 passed / 0 failed.
- Commits: c939e09 (stage 1), 6ada025 (stage 2), 6b5a6e7 (stage 3), fb05429 (stage 4).
