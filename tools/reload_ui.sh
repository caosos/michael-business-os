#!/usr/bin/env bash
# One controlled UI-only reload of the Operator UI (mbos-dev-ui, :8766) to an exact lane 06 commit, with backup and automatic rollback.
# NOT RUN without the owner's explicit approval (see docs/handoff/LIVE_RELOAD_PACKET_8766.md). Touches ONLY the mbos-dev-ui tmux session and
# var/lanes/agent-06/{operator_ui,comms_spec}. Database, worker, approvals, receipts, other services: untouched.
# usage: tools/reload_ui.sh <lane06-commit-sha>
set -u
SHA="${1:?usage: tools/reload_ui.sh <lane06-commit-sha>}"
cd "$(dirname "$0")/.."
L=var/lanes; STAMP=$(date -u +%Y%m%dT%H%M%SZ); B=$L/agent-06.prev-$STAMP; NEW=$L/agent-06.reload-$STAMP
git fetch -q origin
git cat-file -e "$SHA^{commit}" 2>/dev/null || { echo "unknown commit $SHA"; exit 2; }
git merge-base --is-ancestor "$SHA" origin/research/agent-06-communications || { echo "$SHA is not on origin/research/agent-06-communications"; exit 2; }
if ps -eo args | grep -E '[t]ools/worker.py|[c]laude -p You are a fresh' | grep -v 'bash -c' >/dev/null; then echo "a worker is running; wait for it (reload stops nothing else, but keep the window quiet)"; fi
mkdir -p "$NEW" && git archive "$SHA" operator_ui comms_spec | tar -x -C "$NEW" || { echo "export failed"; exit 2; }
cp -a $L/agent-06 "$B" && echo "backup: $B"
start_ui(){ tmux new-session -d -s mbos-dev-ui "cd $PWD && set -a && . var/dev.env && . var/owner.env && set +a && MBOS_OPERATOR_PIN=\$(cat var/ui.pin) exec .venv/bin/python -u -m operator_ui serve --port 8766 2>&1 | tee -a var/ui.log"; }
date -u +"stop %FT%TZ"
tmux kill-session -t mbos-dev-ui 2>/dev/null; sleep 2
rm -rf $L/agent-06/operator_ui $L/agent-06/comms_spec
cp -a "$NEW/operator_ui" "$NEW/comms_spec" $L/agent-06/
start_ui; sleep 9
code=$(curl -s -m 10 -o /dev/null -w "%{http_code}" http://127.0.0.1:8766/market); echo "8766/market -> $code"
if [ "$code" != "200" ]; then
  echo "ROLLBACK to $B"; tmux kill-session -t mbos-dev-ui 2>/dev/null; rm -rf $L/agent-06; cp -a "$B" $L/agent-06; start_ui; sleep 8
  curl -s -m 10 -o /dev/null -w "after rollback / -> %{http_code}\n" http://127.0.0.1:8766/; exit 1
fi
rm -rf "$NEW"; date -u +"done %FT%TZ (code $SHA, rollback copy $B)"
