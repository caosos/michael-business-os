# Pickup watcher: survive reboot and logout (PREPARED, NOT INSTALLED)

Today: tmux session `mbos-pickup` under account `michaelos` (no user systemd units exist; `Linger=no`), so a reboot stops it. The watcher is safe to restart at any time between instructions: state is in `var/pickup/state.json`, and an id that is already acknowledged is never run twice.

## Facts checked on this machine (2026-10-10)
- Git pushes use `git@github-michaelos` with `~/.ssh/id_ed25519_michaelos`, **no passphrase, no ssh-agent needed**: works at boot.
- Claude login is file-based (`~/.claude/.credentials.json`, mode 600): works without a desktop session (not the keyring).
- `claude` is `~/.local/bin/claude`; the unit sets PATH explicitly (systemd user units have a minimal PATH).
- systemd 249 supports `systemctl --user`. The watcher already re-execs itself when its own code changes, so deploys need no restart.

## The changes required (all within the `michaelos` account, in this order)
1. Install the unit: `mkdir -p ~/.config/systemd/user && cp ~/business-os-worktrees/agent-01-coordinator/ops/systemd/mbos-pickup.service ~/.config/systemd/user/`
2. Allow it to run without a login session (the ONE privileged-looking step): `loginctl enable-linger michaelos` (polkit may ask for the account password; if it refuses, `sudo loginctl enable-linger michaelos`). This changes only user-service lifetime for this account.
3. `systemctl --user daemon-reload`
4. At a safe boundary (no pickup executor running: `ps -eo args | grep '[c]laude -p You are Agent 01'` is empty), stop the tmux watcher: `tmux kill-session -t mbos-pickup`. (The lock file also prevents two watchers, so a mistake cannot double-run.)
5. `systemctl --user enable --now mbos-pickup`
6. Verify: `systemctl --user status mbos-pickup`, then `tail var/pickup/daemon.out` and `cat var/pickup/heartbeat.json`; reboot test later with `loginctl show-user michaelos -p Linger` = yes.

## Rollback
`systemctl --user disable --now mbos-pickup; rm ~/.config/systemd/user/mbos-pickup.service; loginctl disable-linger michaelos`, then start the tmux watcher again with `tmux new-session -d -s mbos-pickup ".venv/bin/python -u -I tools/inbox_pickup.py --interval 60 2>&1 | tee -a var/pickup/daemon.out"`.

## Not changed by this
No new permissions, no sudo rule, no change to the Claude Code settings, no Desktop-Agent involvement, no other services. The other watchers (`mbos-watchdog`, dispatcher, UI, worker) are untouched.
