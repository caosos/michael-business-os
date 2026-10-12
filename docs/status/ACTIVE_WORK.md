# ACTIVE WORK: who is doing what right now

- **Maintained by:** Agent 01. Runtime model: ADR-0014 (only Agent 01 is persistent; lanes 02-07 are bounded workers per task).
- **REFRESHED 2026-10-11T22:22:40Z (host observation by Agent 01).** The 2026-10-08 table and its "RUN PAUSED ON QUOTA" / old-blocker text further down are **SUPERSEDED** and kept only as audit history.
- **Host at 2026-10-11T22:22:40Z:** tmux `mbos-agent-01`, `mbos-watchdog`, `mbos-dev-worker`, `mbos-dev-ui`, `mbos-pickup` present; **no bounded worker process is running** (the F-143 worker exited 2026-10-11T22:06:17Z, pushed `315ddfa`); every MBOS worktree clean and in sync with its remote. Live UI `:8766` loaded `85246899` (F-142), PID 725190; F-143 `315ddfa` is verified but NOT loaded (reload run denied by the permission classifier 22:18Z; owner NEED recorded).
- **Pushed heads:** 01 `579a9bc` · 02 `0d40ed5` · 03 `4bc91f3` · 04 `46403f1` · 05 `44a0fb2` · 06 `315ddfa` · 07 `96e4c68`.

## Active claims (actual)
| Task | Lane | State | Evidence |
|---|---|---|---|
| F-143 | 06 | STAGING_ACCEPTED @ `315ddfa`, release NEED | claim `3c35936`; worker exit 22:06:17Z; receipt `docs/receipts/2026-10-11-f143-clean-commit-verification.md` |
| B-12 | 02 | BLOCKED on the live-acceptance NEED (mailbox, 4 prerequisites absent at 21:36:49Z) | `docs/handoff/B12_LOCAL_SOURCE_WIRING_SPEC.md` |
| F-145 | 06 | see READY_QUEUE (B-12 wiring sub-step, implementable without a mailbox) | queue row |

All other lanes: CLOSED, nothing READY (all open rows BLOCKED on owner/host). Lane statuses that still read CLOSED / "F-142 reload NEED" (06) or "B-12 needs Michael #8" (02) are history on their own branches; the current truth is this file. Corrections are routed to the owning lanes through their next worker, not by rewriting their history.

---
## SUPERSEDED 2026-10-08 table (audit history, do not read as current)

- **Maintained by:** Agent 01. Runtime model: ADR-0014. Only Agent 01 is a persistent session; lanes 02-07 are fresh bounded workers launched per task (`tools/worker.py`), so this table shows lane state, not live sessions.
- **Last synced:** 2026-10-08 against lane heads 02 `55a7e19` · 03 `0de7fa5` · 04 `819b5c7` · 05 `4f12ab7` · 06 `6a16af0` · 07 `e8f8fa4` (refresh: `tools/foreman.py --reconcile`).

| Lane | State | Last bounded worker result | READY work | Blocker |
|---|---|---|---|---|
| **01** Coordinator (persistent) | WORKING | A-35, A-33/34, gate green (437) | none open | none |
| **02** Discovery | CLOSED (worker per task) | P-02-15 `349f21c` | none | B-12 live smoke: credentials + MICHAEL_DECISIONS #8 |
| **03** Economics | CLOSED | P-03-17 `276ecd4` | none | MICHAEL_DECISIONS #9 (class thresholds) |
| **04** State | CLOSED | P-06-19 `0dbddaa` (migration 0018) | none | D-09b/D-19/D-20: off-box destination (#11); D-21: CRM decision; D-22: linger + Podman (host) |
| **05** Governance | CLOSED | E-17..E-19 | none | E-20/E-21: Michael's `licenses_held`; E-22: host software |
| **06** Operator UI | CLOSED | P-06-18 partial -> P-06-19 done | re-run P-06-18's human-outcome test now that 0018 landed | none |
| **07** QA | CLOSED (fresh worker per release window) | G-14 `2e1e5f8` (RC READY, 0 residual xfails) | next release window | none |

**RUN PAUSED ON QUOTA (5-hour window 97%, resets 19:20Z); see `docs/status/STATE_OF_PLAY.md`.** Previously: useful READY work was exhausted (2026-10-08, after the R14-in-the-database sequence D-23..D-28, G-16..G-19; gate green 443; 25+ bounded workers) except the owner-gated items above and the P-06-18 re-run. Next dispatch happens when Michael answers #9/#10/#11, supplies credentials, or a new gap is found.


## Current checkpoint — 2026-10-12 01:10 America/Chicago

- Loaded Marketplace artifact: `bbc80ec851b75aec52af1f8b0838dd56ccc714ef`; Agent 01 live verification recorded 2026-10-12T06:03:14Z, listener PID 1233443.
- Current bounded implementation: F-155 Suggestions, existing lane 06 worker path; corrected relaunch receipt `45ba39d0fbf94777 #16`; current host liveness UNKNOWN; next_check_at 2026-10-12 02:01 America/Chicago.
- F-154 acceptance gate: NEED after missed 01:08 checkpoint; no F-154 worker observed at 2026-10-12T06:09:33Z. Code exists, but full coordinator suite and live desktop/mobile Claude Chrome acceptance are missing. **APPEARS STALE — HOST STATE UNVERIFIED.**
- No duplicate worker, queue, coordinator, watchdog or monitor. Michael must do NOTHING.
