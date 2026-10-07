#!/usr/bin/env bash
# Both suites, in separate processes (DBOS is a per-process singleton). Non-zero if either fails.
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
$PY -m pytest -q tests -p no:cacheprovider; a=$?
MBOS_UI_LANE_D=1 $PY -m pytest -q tests -p no:cacheprovider; b=$?
echo "reference backend: exit $a · lane D + lane E: exit $b"
exit $(( a || b ))
