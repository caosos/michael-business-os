#!/usr/bin/env bash
# One controlled UI-only reload of the Operator UI (mbos-dev-ui) to an EXACT lane 06 commit, with a verified backup, verified artifact identity and
# automatic rollback. NOT RUN without the owner's explicit approval (docs/handoff/LIVE_RELOAD_PACKET_8766.md). It touches only the mbos-dev-ui tmux
# session and var/lanes/agent-06/{operator_ui,comms_spec}; database, worker, approvals, receipts and other services are never touched.
#
#   tools/reload_ui.sh <lane06-commit-sha>            reload (aborts before ANY live change unless export + backup are verified)
#   tools/reload_ui.sh --verify-only <port>           read-only semantic checks of a running UI (e.g. a staging port); changes nothing
#
# Test seams (never touch live): MBOS_RELOAD_PORT, MBOS_RELOAD_SLEEP_STOP, MBOS_RELOAD_SLEEP_START; tmux and curl are looked up on PATH (tests shim them).
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${MBOS_RELOAD_PORT:-8766}"; SLEEP_STOP="${MBOS_RELOAD_SLEEP_STOP:-2}"; SLEEP_START="${MBOS_RELOAD_SLEEP_START:-9}"
BASE="http://127.0.0.1"
L=var/lanes; LIVE=$L/agent-06

# What the served pages must show (semantic, not just HTTP 200). Markers come from the F-56/F-57 behaviour.
verify_pages() {  # $1 = port; prints a reason and returns 1 on the first failed check
  local port="$1" body code redirect
  redirect=$(curl -s -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' "$BASE:$port/") || { echo "GET / failed"; return 1; }
  case "$redirect" in "303 "*"/market") ;; *) echo "GET / is '$redirect', expected a 303 to /market"; return 1;; esac
  body=$(curl -s -m 20 "$BASE:$port/market") || { echo "GET /market failed"; return 1; }
  for m in "Michael's Marketplace" "name='cat'" "name='row1'" "name='row4'" "name='condition'" "name='any'" "Save this search" "Gallery rows"; do
    case "$body" in *"$m"*) ;; *) echo "/market is missing the marker: $m"; return 1;; esac
  done
  body=$(curl -s -m 20 "$BASE:$port/market?go=1&source=gsa&radius=-1") || { echo "validation route failed"; return 1; }
  case "$body" in *filter-errors*) ;; *) echo "a negative radius did not show the validation message (filter-errors)"; return 1;; esac
  for route in /mission /queue; do
    body=$(curl -s -m 20 "$BASE:$port$route") || { echo "GET $route failed"; return 1; }
    if printf '%s' "$body" | grep -qiE 'TRAIN-|example\.invalid|55 inch|LED TV'; then echo "$route shows fictional training content"; return 1; fi
  done
  return 0
}

tree_hash() {  # $1 = dir holding operator_ui/ and comms_spec/
  (cd "$1" && find operator_ui comms_spec -type f ! -name '*.pyc' ! -path '*/__pycache__/*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)
}

if [ "${1:-}" = "--verify-only" ]; then
  reason=$(verify_pages "${2:?usage: --verify-only <port>}") && { echo "VERIFY OK on port $2"; exit 0; }
  echo "VERIFY FAILED on port $2: $reason"; exit 1
fi

SHA="${1:?usage: tools/reload_ui.sh <lane06-commit-sha> | --verify-only <port>}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ); B=$L/agent-06.prev-$STAMP; NEW=var/reload/$STAMP
abort() { echo "ABORT before any live change (nothing stopped, nothing removed): $*"; rm -rf "$NEW"; exit 2; }

# ---- prerequisites: every one must pass BEFORE the UI is stopped or any live file is touched ----
git fetch -q origin || abort "git fetch failed"
git cat-file -e "$SHA^{commit}" 2>/dev/null || abort "unknown commit $SHA"
git merge-base --is-ancestor "$SHA" origin/research/agent-06-communications || abort "$SHA is not on origin/research/agent-06-communications"
[ -s "$LIVE/operator_ui/server.py" ] && [ -d "$LIVE/comms_spec" ] || abort "the live UI directory $LIVE is missing or incomplete"
mkdir -p "$NEW" || abort "cannot create $NEW"
git archive "$SHA" operator_ui comms_spec | tar -x -C "$NEW" || abort "export of $SHA failed"
for need in operator_ui/server.py operator_ui/market_view.py operator_ui/market_search.py comms_spec; do
  [ -s "$NEW/$need" ] || [ -d "$NEW/$need" ] || abort "the export of $SHA lacks $need"
done
[ -n "$(find "$NEW/operator_ui" -name '*.py' | head -1)" ] || abort "the exported operator_ui has no python files"
cp -a "$LIVE" "$B" || abort "backup copy to $B failed"
diff -rq --exclude='__pycache__' --exclude='*.pyc' "$LIVE" "$B" >/dev/null || abort "the backup $B differs from the live UI"
[ "$(find "$LIVE" -type f ! -name '*.pyc' ! -path '*/__pycache__/*' | wc -l)" = "$(find "$B" -type f ! -name '*.pyc' ! -path '*/__pycache__/*' | wc -l)" ] || abort "the backup file count differs"
EXPECT_TREE=$(tree_hash "$NEW") || abort "cannot hash the exported artifact"
printf 'sha=%s\ntree_sha256=%s\nexported_utc=%s\n' "$SHA" "$EXPECT_TREE" "$STAMP" > "$NEW/ARTIFACT"
echo "prerequisites OK: export $SHA tree $EXPECT_TREE; verified backup $B"
if ps -eo args | grep -E '[t]ools/worker.py|[c]laude -p You are a fresh' | grep -v 'bash -c' >/dev/null; then echo "note: a worker is running (the reload does not stop it)"; fi

# ---- point of no return ----
start_ui() { tmux new-session -d -s mbos-dev-ui "cd $PWD && set -a && . var/dev.env && . var/owner.env && set +a && MBOS_OPERATOR_PIN=\$(cat var/ui.pin) exec .venv/bin/python -u -m operator_ui serve --port $PORT 2>&1 | tee -a var/ui.log"; }
rollback() {
  echo "ROLLBACK to $B ($1)"
  tmux kill-session -t mbos-dev-ui 2>/dev/null || true
  rm -rf "$LIVE" && cp -a "$B" "$LIVE" && start_ui && sleep "$SLEEP_START" \
    && [ "$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$BASE:$PORT/")" != "000" ] \
    && { echo "rollback done: the previous UI answers; backup kept at $B"; exit 1; }
  echo "ROLLBACK FAILED: restore by hand: rm -rf $LIVE; cp -a $B $LIVE; then start mbos-dev-ui as in tools/run_dev_stack.sh. Backup kept at $B"; exit 3
}
date -u +"stop %FT%TZ"
tmux kill-session -t mbos-dev-ui 2>/dev/null || true; sleep "$SLEEP_STOP"
rm -rf "$LIVE/operator_ui" "$LIVE/comms_spec"
cp -a "$NEW/operator_ui" "$NEW/comms_spec" "$LIVE/" || rollback "copying the artifact into place failed"
cp "$NEW/ARTIFACT" "$LIVE/ARTIFACT" || rollback "writing the artifact marker failed"
start_ui || rollback "starting the UI failed"
sleep "$SLEEP_START"

# ---- post-reload proof: identity AND behaviour, not HTTP 200 alone ----
GOT_TREE=$(tree_hash "$LIVE") || rollback "cannot hash the served files"
[ "$GOT_TREE" = "$EXPECT_TREE" ] || rollback "the files on disk are not the artifact (tree $GOT_TREE, expected $EXPECT_TREE)"
grep -q "^sha=$SHA\$" "$LIVE/ARTIFACT" || rollback "the artifact marker does not name $SHA"
tmux has-session -t mbos-dev-ui 2>/dev/null || rollback "the mbos-dev-ui session is not running"
reason=$(verify_pages "$PORT") || rollback "semantic check failed: $reason"
rm -rf "$NEW"
date -u +"done %FT%TZ: serving $SHA (tree $GOT_TREE); rollback copy kept at $B"
