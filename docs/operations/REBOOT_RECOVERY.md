# Reboot recovery (user-level, account `michaelos`)

Five user units restore the EXISTING tmux sessions after a reboot. They supersede the pickup-only plan in `PICKUP_PERSISTENCE.md`.

| Unit | tmux session | Starts |
|---|---|---|
| `mbos-agent-01.service` | `mbos-agent-01` | `~/bin/mbos-agent 1` (the single coordinator) |
| `mbos-watchdog.service` | `mbos-watchdog` | `tools/coordinator_watch.py --interval 120 --serve-port 8479` with `MBOS_ALLOW_TMUX_WAKE=1` (wake on) |
| `mbos-dev-worker.service` | `mbos-dev-worker` | project Postgres (`pgserver`, no bootstrap) then `mbos worker` |
| `mbos-dev-ui.service` | `mbos-dev-ui` | project Postgres then Operator UI on `:8766` |
| `mbos-pickup.service` | `mbos-pickup` | `tools/inbox_pickup.py --interval 60` |

The dispatcher is not a unit: the watchdog starts `mbos-dispatcher` when compatible READY work exists.

Each unit is `Type=oneshot` + `RemainAfterExit` and calls `ops/systemd/mbos-ensure-tmux.sh <name>`, which starts the session only if `tmux has-session` says it is absent. `active` therefore means "the guard ran and the session exists", and a manual `systemctl --user start` can never create a duplicate. Postgres is started with `pgserver.get_server(.pgdata, cleanup_mode=None)`; `tools/bootstrap_dev.py` is NOT re-run because it rewrites `var/dev.env` and `var/owner.env`.

Install / check / rollback (user-level only, no sudo):
```bash
ops/systemd/install_user_units.sh              # copies to ~/.config/systemd/user, daemon-reload, enable (starts nothing)
systemctl --user is-enabled mbos-watchdog.service; systemctl --user is-active mbos-watchdog.service
ops/systemd/install_user_units.sh --uninstall  # disable + remove
```
Needs `Linger=yes` (`loginctl show-user michaelos -p Linger`) so the units run with no login session.

After a reboot verify: `tmux ls` (five sessions), `curl http://127.0.0.1:8479/health.json`, `curl -I http://127.0.0.1:8766/`, `git fetch && ls var/next_work_arm.jsonl`. The `next_work.py` Monitor feed is session-bound and is re-armed by the Agent 01 session itself (A-69).
