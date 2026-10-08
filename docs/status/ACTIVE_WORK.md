# ACTIVE WORK: who is doing what right now

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
