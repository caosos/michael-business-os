#!/usr/bin/env bash
# Isolated STAGING UI for firsthand Claude-in-Chrome acceptance (owner-started: Agent 01's sandbox-local servers are unreachable from the
# owner's Chrome, and starting one outside the sandbox is refused by the permission classifier).
#   tools/stage_ui.sh <lane06-sha> <lane02-sha> [port=8790]     start (replaces only an earlier staging session)
#   tools/stage_ui.sh --stop                                     stop it
# What it is: the exact lane 06 commit exported to var/stage/<sha>, run with the coordinator venv's Python and lane 02's exact source on the
# path, a STUB decision store (no database), COPIES of the GSA and auction-house caches, the fixture flags for alert/bid e-mails, on
# 127.0.0.1 only, in tmux session `mbos-stage`. It never touches :8766, the live caches, the venv packages or the database.
set -euo pipefail
cd "$(dirname "$0")/.."
SESSION=mbos-stage
if [ "${1:-}" = "--stop" ]; then tmux kill-session -t "$SESSION" 2>/dev/null && echo "staging stopped" || echo "no staging session"; exit 0; fi
SHA06="${1:?usage: tools/stage_ui.sh <lane06-sha> <lane02-sha> [port]}"; SHA02="${2:?lane02 sha}"; PORT="${3:-8790}"
[ "$PORT" != 8766 ] || { echo "ABORT: 8766 is the live UI"; exit 2; }
git fetch -q origin
git merge-base --is-ancestor "$SHA06" origin/research/agent-06-communications || { echo "ABORT: $SHA06 not on lane 06"; exit 2; }
git merge-base --is-ancestor "$SHA02" origin/research/agent-02-opportunity || { echo "ABORT: $SHA02 not on lane 02"; exit 2; }
ST="var/stage/$SHA06"; L02="var/stage/lane02-$SHA02"; DATA="var/stage/data-$SHA06"
rm -rf "$ST" "$L02" "$DATA"; mkdir -p "$ST" "$L02" "$DATA"
git archive "$SHA06" | tar -x -C "$ST"
git archive "$SHA02" src | tar -x -C "$L02"
cp var/cache/gsa-active-auctions.json "$DATA/gsa.json"; cp var/cache/gsa-active-auctions.asof "$DATA/gsa.asof"
for n in wooley wilson blackmon; do f="var/lanes/agent-06/var/cache/$n-events.json"; [ -f "$f" ] && cp "$f" "$DATA/$n-events.json" || true; done
missing=$(for n in wooley wilson blackmon; do [ -f "$DATA/$n-events.json" ] || printf '%s ' $n; done)
if [ -n "$missing" ]; then                        # no live cache yet (release not run): fetch once into the STAGING folder with the artifact's own tool
  echo "no cached events for: $missing; refreshing them once into $DATA (auctioneers' own sites only; Blackmon takes about 5 minutes)"
  for n in $missing; do U=$(echo $n | tr a-z A-Z); env MBOS_${U}_CACHE=$PWD/$DATA/$n-events.json .venv/bin/python -c "import sys; sys.path[:0]=['$PWD/$L02/src','$PWD/$ST']; sys.argv=['refresh','--live','--only','$n']; import runpy; runpy.run_path('$PWD/$ST/tools/refresh_auction_events.py', run_name='__main__')" || echo "refresh of $n failed (staging shows it offline)"; done
fi
cat > "$DATA/serve.py" <<'PY'
import os, sys
from http.server import ThreadingHTTPServer
root, port, data, lane02 = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path[:0] = [lane02, root]                     # lane 02's exact source first, then the staged lane 06 tree (-I ignores PYTHONPATH)
os.environ.update(MBOS_MARKET_PREFS_FILE=f"{data}/prefs.json", MBOS_GSA_CACHE=f"{data}/gsa.json")
from operator_ui.server import App, make_handler
from tests.test_wanted_f23 import GOV_POLICY, StubStore
if not hasattr(StubStore, "action_requests"):
    StubStore.action_requests = lambda self, *a, **k: []
app = App(StubStore(), operator_pin="000000", campaigns_file=f"{data}/campaigns.json", policy_path=str(GOV_POLICY) if GOV_POLICY else None)
print(f"STAGING (stub store, cache copies, fixture flags) on http://127.0.0.1:{port}/market", flush=True)
ThreadingHTTPServer(("127.0.0.1", port), make_handler(app)).serve_forever()
PY
tmux kill-session -t "$SESSION" 2>/dev/null || true
ENVS="MBOS_STAGING_FIXTURES=1 MBOS_BID_MAIL_DIR=$PWD/$ST/tests/fixtures/bid_mail MBOS_MARKET_FIXTURE_MAIL_DIR=$PWD/$ST/tests/fixtures/alerts"
for n in wooley wilson blackmon; do U=$(echo $n | tr a-z A-Z); [ -f "$DATA/$n-events.json" ] && ENVS="$ENVS MBOS_${U}_CACHE=$PWD/$DATA/$n-events.json"; done
tmux new-session -d -s "$SESSION" "cd $PWD && env $ENVS .venv/bin/python -I $DATA/serve.py $PWD/$ST $PORT $PWD/$DATA $PWD/$L02/src 2>&1 | tee $DATA/stage.log"
sleep 4
code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/market" || true)
echo "staging $SHA06 (+ lane 02 $SHA02) on http://127.0.0.1:$PORT/market -> HTTP $code (tmux session $SESSION; stop with tools/stage_ui.sh --stop)"
[ "$code" = 200 ]
