#!/usr/bin/env bash
# DealSniffer rollback. Never deletes data (/var/lib/dealsniffer), secrets or other apps.
#   sudo bash deploy/linode/rollback.sh site       take dealsniffers.com off nginx (site file kept in sites-available)
#   sudo bash deploy/linode/rollback.sh stop       stop and disable the dealsniffer service
#   sudo bash deploy/linode/rollback.sh previous   point /opt/dealsniffer/current back at the previous release and restart
# Full removal is manual and deliberate; see deploy/linode/README.md "Uninstall".
set -euo pipefail
R="${DS_ROOT:-}"; OPT="$R/opt/dealsniffer"
[ -n "${DS_TEST:-}" ] || [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
case "${1:-}" in
  site)
    rm -f /etc/nginx/sites-enabled/dealsniffers.com
    nginx -t && systemctl reload nginx && echo "dealsniffers.com removed from nginx (other sites unchanged)";;
  stop)
    systemctl disable --now dealsniffer && echo "dealsniffer stopped and disabled";;
  previous)
    [ -L "$OPT/previous" ] || { echo "STOP: no previous release recorded"; exit 1; }
    p="$(readlink "$OPT/previous")"; c="$(readlink "$OPT/current")"
    [ -f "$p/BUILD_INFO" ] || { echo "STOP: previous release $p is incomplete"; exit 1; }
    ln -sfn "$p" "$OPT/current.tmp" && mv -Tf "$OPT/current.tmp" "$OPT/current"; ln -sfn "$c" "$OPT/previous"
    echo "current -> $p (previous -> $c)"
    [ -n "${DS_TEST:-}" ] || { systemctl restart dealsniffer && echo "service restarted"; };;
  *) echo "usage: $0 site|stop|previous"; exit 2;;
esac
