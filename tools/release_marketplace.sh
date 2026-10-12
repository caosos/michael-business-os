#!/usr/bin/env bash
# One-command combined Marketplace release (owner-run; Agent 01's runs of reload_ui.sh are denied by the Claude Code permission classifier).
#   tools/release_marketplace.sh <lane06-sha> <lane02-sha> [--dry]
# Steps, each checked; nothing outside these:
#   1. both SHAs must be on the pushed lane branches;
#   2. back up the coordinator venv's current `mbos_discovery` package, then install lane 02 <lane02-sha> into it offline (no deps);
#      the running UI keeps its already-imported modules until step 3 restarts it;
#   3. tools/reload_ui.sh <lane06-sha> (verified backup, artifact identity, automatic rollback; unchanged behaviour);
#      if it does not succeed, the previous `mbos_discovery` package is restored before exiting;
#   4. refresh the auction-house caches on the live path with the artifact's own tools/refresh_auction_events.py --live
#      (fetches only the auctioneers' own sites; a failed refresh keeps the old cache).
# --dry prints the plan and the checks without changing anything.
set -euo pipefail
cd "$(dirname "$0")/.."
SHA06="${1:?usage: tools/release_marketplace.sh <lane06-sha> <lane02-sha> [--dry]}"; SHA02="${2:?lane02 sha}"; DRY="${3:-}"
PY=.venv/bin/python; SITE=$($PY -c 'import sysconfig;print(sysconfig.get_paths()["purelib"])'); PKG="$SITE/mbos_discovery"
STAMP=$(date -u +%Y%m%dT%H%M%SZ); BK="var/release-backups/mbos_discovery.prev-$STAMP"; SRC="var/release-backups/disc-$SHA02"
git fetch -q origin
git merge-base --is-ancestor "$SHA06" origin/research/agent-06-communications || { echo "ABORT: $SHA06 is not on the pushed lane 06 branch"; exit 2; }
git merge-base --is-ancestor "$SHA02" origin/research/agent-02-opportunity || { echo "ABORT: $SHA02 is not on the pushed lane 02 branch"; exit 2; }
[ -d "$PKG" ] || { echo "ABORT: $PKG not found"; exit 2; }
echo "plan: lane06 $SHA06 | lane02 $SHA02 | venv package $PKG | package backup $BK"
if [ "$DRY" = "--dry" ]; then echo "DRY: checks passed; nothing changed"; exit 0; fi

mkdir -p var/release-backups && cp -a "$PKG" "$BK" && diff -rq "$PKG" "$BK" >/dev/null || { echo "ABORT: package backup failed"; exit 2; }
restore_pkg() { rm -rf "$PKG" && cp -a "$BK" "$PKG" && echo "restored the previous mbos_discovery package from $BK"; }
rm -rf "$SRC" && mkdir -p "$SRC" && git archive "$SHA02" | tar -x -C "$SRC" && rm -rf "$SRC/build"
UV_CACHE_DIR=.tools/uv-cache .tools/uv pip install -q --offline --no-deps --reinstall --python "$PY" "$SRC" || { restore_pkg; echo "ABORT: install failed; nothing else changed"; exit 2; }
$PY -c "import mbos_discovery.adapters.wooley_site, mbos_discovery.adapters.wilson_site" || { restore_pkg; echo "ABORT: new package does not import; restored"; exit 2; }
echo "installed lane 02 $SHA02 into the coordinator venv"

if ! tools/reload_ui.sh "$SHA06"; then restore_pkg; echo "RELEASE NOT DONE: reload_ui.sh did not succeed (see above; it rolled the UI back); package restored"; exit 1; fi

mkdir -p var/lanes/agent-06/tools && git show "$SHA06:tools/refresh_auction_events.py" > var/lanes/agent-06/tools/refresh_auction_events.py
$PY var/lanes/agent-06/tools/refresh_auction_events.py --live || echo "WARNING: an auction refresh reported an error (the UI is released; an old or missing cache shows as offline honestly)"
echo "RELEASED: UI $SHA06 with lane 02 $SHA02; auction caches refreshed. Package backup kept at $BK"
