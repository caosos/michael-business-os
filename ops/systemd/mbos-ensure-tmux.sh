#!/usr/bin/env bash
# Start ONE named tmux session for the MBOS stack if (and only if) it is not already running.
# Used by the mbos-*.service user units so a reboot restores the existing sessions and a manual
# `systemctl --user start` can never create a duplicate. Usage: mbos-ensure-tmux.sh <agent-01|watchdog|dev-worker|dev-ui|pickup>
set -euo pipefail
ROOT="$HOME/business-os-worktrees/agent-01-coordinator"
cd "$ROOT"
what="${1:?usage: mbos-ensure-tmux.sh <agent-01|watchdog|dev-worker|dev-ui|pickup>}"

devdb_up() {  # start the project-local Postgres WITHOUT regenerating var/dev.env or var/owner.env (bootstrap_dev would)
  "$ROOT/.venv/bin/python" -I -c "import pgserver; pgserver.get_server('$ROOT/.pgdata', cleanup_mode=None)"
}

pre=""
case "$what" in
  agent-01)   session=mbos-agent-01;  cmd="$HOME/bin/mbos-agent 1" ;;
  watchdog)   session=mbos-watchdog;  cmd="cd $ROOT && MBOS_ALLOW_TMUX_WAKE=1 exec .venv/bin/python -u -I tools/coordinator_watch.py --interval 120 --serve-port 8479 2>&1 | tee -a var/watchdog/daemon.out" ;;
  dev-worker) session=mbos-dev-worker; pre=devdb_up
              cmd="cd $ROOT && set -a && . var/dev.env && set +a && exec .venv/bin/python -u -m mbos.cli worker 2>&1 | tee -a var/worker.log" ;;
  dev-ui)     session=mbos-dev-ui;    pre=devdb_up
              cmd="cd $ROOT && set -a && . var/dev.env && . var/owner.env && set +a && MBOS_OPERATOR_PIN=\$(cat var/ui.pin) exec .venv/bin/python -u -m operator_ui serve --port 8766 2>&1 | tee -a var/ui.log" ;;
  pickup)     session=mbos-pickup
              cmd="cd $ROOT && .venv/bin/python -u -I tools/inbox_pickup.py --interval 60 2>&1 | tee -a var/pickup/daemon.out" ;;
  *) echo "unknown target: $what" >&2; exit 2 ;;
esac

if tmux has-session -t "$session" 2>/dev/null; then
  echo "$(date -Is) $session already running; nothing to do"
  exit 0
fi
[ -z "$pre" ] || "$pre"
tmux new-session -d -s "$session" "$cmd"
echo "$(date -Is) started $session"
