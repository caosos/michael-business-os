# Pickup receipt: ARYA-20261010-0328-f49-verification

Executor: Agent 01 automatic inbox executor, docs-only, dry-run.

## What I did
- Fetched origin. Lane 06 head is still `b1a3d16` (F-49 code `820854c`), so the earlier verification is current and no re-run was needed.
- Confirmed READY_QUEUE is reconciled: F-49 is recorded as code and staging done, not live. F-50 (P1, lane 06) is queued for the caveat defect and the D+E test failure.
- Confirmed the full receipt exists: `docs/receipts/2026-10-10-f49-verification.md`.

## Evidence and numbers (from that receipt, not re-run here)
- Staging :8767: 17 non-demo routes returned HTTP 200 with 0 fiction/TRAIN-/example.invalid hits. ZIP 72032 and "Conway, AR" resolve to Conway. Unsupported places say plainly that they are not located.
- Reference suite: 314 passed, 1 failed. The failure is a resale_f39 socket timeout that passes alone (4 of 4), and it also failed on F-48.
- Lane D+E: 104 passed, 3 failed. Two are the known F-32 failures. The third (`test_wanted_f25 double_submit`) fails identically on F-48 head `5b42655`, so it is not an F-49 regression. Its cause is unknown and it is queued under F-50.
- Live :8766 (read-only): still the F-48 export, with 1 fiction hit each on /mission, /summary, /digest and /ledger. F-49 is not live.

## Remaining blockers
- Defect for lane 06 (F-50): there is no visible approximate-centroid / limited-coverage caveat on /market.
- Owner decision needed for live acceptance: one UI-only reload of `mbos-dev-ui`, about 11 s, only that tmux session.
  - Artifact: `research/agent-06-communications` @ `b1a3d16`, copied from `var/lanes/agent-06.new` over `var/lanes/agent-06`.
  - Rollback: restore the timestamped backup. Database and worker are untouched.
  - The F-48 reload authorization (02:04Z) was used and does not cover this. Recommend waiting for F-50 so one reload covers both.
