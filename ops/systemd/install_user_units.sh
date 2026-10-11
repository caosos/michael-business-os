#!/usr/bin/env bash
# Install + enable (NOT start) the MBOS user units for account michaelos. User-level only: no sudo, no system units.
# Enabling starts nothing now; sessions already running stay untouched. Rollback: --uninstall.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"; DST="$HOME/.config/systemd/user"
UNITS="mbos-agent-01 mbos-watchdog mbos-dev-worker mbos-dev-ui mbos-pickup"
if [ "${1:-}" = "--uninstall" ]; then
  for u in $UNITS; do systemctl --user disable "$u.service" 2>/dev/null || true; rm -f "$DST/$u.service"; done
  systemctl --user daemon-reload; exit 0
fi
mkdir -p "$DST"
for u in $UNITS; do cp "$SRC/$u.service" "$DST/$u.service"; done
systemctl --user daemon-reload
for u in $UNITS; do systemctl --user enable "$u.service"; done
loginctl show-user "$USER" -p Linger
