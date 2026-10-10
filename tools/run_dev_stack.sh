#!/usr/bin/env bash
# Start (or restart) the DRY-RUN Deal Sniffer stack in tmux so Michael never has to open a terminal:
#   mbos-dev-worker  : the workflow worker (real lanes; NO fixtures unless MBOS_DEMO=1; NO owner login)
#   mbos-dev-ui      : the Operator UI (owner login + PIN from var/ui.pin), http://127.0.0.1:${PORT:-8766}/
# Normal start injects NO training fixtures (they are invented, example.invalid). MBOS_DEMO=1 tools/run_dev_stack.sh start loads them for testing only.
# Usage: tools/run_dev_stack.sh [start|stop|status]. Everything is DRY-RUN; nothing leaves this machine.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8766}"
case "${1:-start}" in
  stop)   tmux kill-session -t mbos-dev-worker 2>/dev/null || true; tmux kill-session -t mbos-dev-ui 2>/dev/null || true; echo stopped ;;
  status) tmux ls 2>/dev/null | grep mbos-dev || echo "stack not running"; curl -s -m 3 -o /dev/null -w "ui http %{http_code}\n" "http://127.0.0.1:${PORT}/" || echo "ui not reachable" ;;
  start)
    [ -f var/dev.env ] && [ -f var/owner.env ] && [ -f var/ui.pin ] || { echo "run: .venv/bin/python -I tools/bootstrap_dev.py --ui-pin <pin>  (and save the pin in var/ui.pin)"; exit 2; }
    tmux kill-session -t mbos-dev-worker 2>/dev/null || true; tmux kill-session -t mbos-dev-ui 2>/dev/null || true
    FIXTURE_ARG=""; [ "${MBOS_DEMO:-0}" = "1" ] && FIXTURE_ARG="--fixture fixtures/sources/training_examples.json" && echo "DEMO MODE: training fixtures loaded, NOT real listings"
    # worker: dev.env only (never the owner DSN: mbos worker refuses it)
    tmux new-session -d -s mbos-dev-worker "cd $PWD && set -a && . var/dev.env && set +a && exec .venv/bin/python -u -m mbos.cli worker ${FIXTURE_ARG} 2>&1 | tee -a var/worker.log"
    tmux new-session -d -s mbos-dev-ui "cd $PWD && set -a && . var/dev.env && . var/owner.env && set +a && MBOS_OPERATOR_PIN=\$(cat var/ui.pin) exec .venv/bin/python -u -m operator_ui serve --port ${PORT} 2>&1 | tee -a var/ui.log"
    sleep 6; "$0" status ;;
esac
