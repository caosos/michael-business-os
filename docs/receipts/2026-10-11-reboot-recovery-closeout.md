# Receipt: reboot recovery closeout (owner directives 2026-10-11 01:34 and 01:59 CDT)

Recorded 2026-10-11T07:54:52Z by Agent 01 from the live session. FACT = observed on this host just now; no external action taken.

## Control chain (FACT)
| Item | Evidence |
|---|---|
| Watchdog health | `http://127.0.0.1:8479/health.json` answered at 2026-10-11T07:53:13Z (schema, panel ok, project `michael_business_os`) |
| Wake enabled | watchdog pid 370126: `MBOS_ALLOW_TMUX_WAKE=1 .venv/bin/python -u -I tools/coordinator_watch.py --interval 120 --serve-port 8479` (no `--no-wake`); `var/watchdog/mode.json` = `{"wake":true,...}` |
| Single coordinator | session `agent-01-coordinator-4f`, claude pid 370112, tmux `mbos-agent-01:@65.%65`, resolved by the watchdog; only one `mbos-agent-01` tmux session exists; loaded coordinator head `bde231f` |
| Dev stack | tmux `mbos-dev-worker` (python pid 358739) and `mbos-dev-ui` (python pid 358744) up ~47 min; `:8766` answers HTTP 303 (login redirect) |
| Dispatcher | `dispatcher_running: false`, `dispatcher_action: NONE`, `approved_ready_rows_for_specialist_lanes: 0`: correctly idle, no duplicate workers |
| Linger | `loginctl show-user michaelos -p Linger` -> `Linger=yes` |
| Delivered -> awake (item 9) | watchdog `last_wake_state: DELIVERED` at 07:53:12Z for the two messages + A-69 + A-70; this existing idle session started the turn immediately, no new session created. Watchdog still lists them unacknowledged until the ACKs in this commit are pushed. |

## NEED (item 7): user-level persistence is not installed
- **Fact:** `~/.config/systemd/user` does not exist; `systemctl --user` has no mbos units. After a reboot only linger survives; the five tmux sessions (`mbos-agent-01`, `mbos-watchdog`, `mbos-dev-worker`, `mbos-dev-ui`, `mbos-pickup`) do not come back by themselves. The only prepared unit is `ops/systemd/mbos-pickup.service` (docs/operations/PICKUP_PERSISTENCE.md).
- **Why not done:** the session's auto-mode permission classifier refused creating the unit files and installer as "Unauthorized Persistence". The owner's liaison message authorizes it, but it arrived as a file, not as a typed instruction in this session, and I did not work around the denial.
- **Exact fix (one decision):** Michael types in this session "install the user-level MBOS persistence units", or adds a Bash permission rule allowing writes under `ops/systemd/` and `~/.config/systemd/user/`. Then I will: add one guarded `ops/systemd/mbos-ensure-tmux.sh` (starts a named tmux session only if absent, so no duplicates; starts the project Postgres with `pgserver` without re-running bootstrap_dev, which rewrites `var/dev.env`/`owner.env`), five Type=oneshot user units that call it, `systemctl --user enable` them (not start), record `is-enabled`/`is-active`, and add a reboot-recovery runbook section. Rollback: disable and delete the units.
- **Continuing meanwhile:** A-69 and A-70 are handled below; other compatible work proceeds.

## Item 7 RESOLVED (2026-10-11T16:26:07Z): user-level persistence installed (owner typed "install the user-level MBOS persistence units")
- Installed to `~/.config/systemd/user/` by `ops/systemd/install_user_units.sh` (no sudo): `mbos-agent-01.service`, `mbos-watchdog.service`, `mbos-dev-worker.service`, `mbos-dev-ui.service`, `mbos-pickup.service`. `Linger=yes`.
- `systemctl --user is-enabled / is-active`: all five **enabled / active**.
- No duplicates: all five were started once while the sessions already ran; `tmux ls` was identical before and after, and the journal shows `mbos-watchdog already running; nothing to do`. Process ids unchanged (watchdog 370129, worker 358739, UI 358744).
- **Not proven:** the cold-start path (an actual reboot). It is exercised only by the next reboot. Runbook: `docs/operations/REBOOT_RECOVERY.md`. Rollback: `install_user_units.sh --uninstall`.
- The repo's earlier `ops/systemd/mbos-pickup.service` (direct python ExecStart) is replaced by the tmux-guard form so the unit cannot fight the running tmux watcher.

## Cold-start test of the units (2026-10-11T16:32:24Z, owner: "reboot them" -> "Restart MBOS sessions only")
Not a host reboot (that would also stop the CAOSCare sessions on this host and needs sudo). The four sessions `mbos-watchdog`, `mbos-dev-worker`, `mbos-dev-ui`, `mbos-pickup` were killed and brought back ONLY by `systemctl --user restart` of their units, so the ensure-script start path (not the already-running no-op) ran for real.
- Result after 12 s: new processes watchdog 592572, worker 592589, UI 592603, pickup 592613; `:8479/health.json` 200; `:8766` 303 (login redirect); worker log shows it recovered and processing the comps inbox; all five units enabled/active; Postgres came up through the unit path.
- Last step: `mbos-agent-01` is restarted by a detached helper (this ends the session that ran the test). The new session's evidence is the `mbos-agent-01` tmux creation time and the watchdog health, recorded in the next receipt.
- Still untested: an actual host reboot (boot ordering, network-online, Linger at boot).
