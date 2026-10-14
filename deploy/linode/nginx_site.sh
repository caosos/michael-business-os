#!/usr/bin/env bash
# Add ONLY the dealsniffers.com nginx site. Every other site is left as it is.
#   sudo bash deploy/linode/nginx_site.sh acme    phase 1: port 80 challenge-only site (before the certificate)
#   sudo bash deploy/linode/nginx_site.sh https   phase 2: https proxy to 127.0.0.1:8765 (needs the certificate)
# Each phase runs `nginx -t` before reloading; if the test fails the DealSniffer file is removed again and nginx is not reloaded.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
AV=/etc/nginx/sites-available/dealsniffers.com; EN=/etc/nginx/sites-enabled/dealsniffers.com; ACME=/var/www/dealsniffer-acme
case "${1:-}" in acme) SRC="$HERE/nginx/dealsniffers.com.acme.conf" ;; https) SRC="$HERE/nginx/dealsniffers.com.conf" ;; *) echo "usage: $0 acme|https"; exit 2 ;; esac
[ -d /etc/nginx/sites-available ] && [ -d /etc/nginx/sites-enabled ] || { echo "STOP: nginx does not use sites-available/sites-enabled here"; exit 1; }
for f in "$AV" "$EN"; do [ ! -e "$f" ] || grep -qs "DealSniffer-managed" "$f" || { echo "STOP: $f exists and is not DealSniffer-managed"; exit 1; }; done
if [ "$1" = https ]; then
  [ -s /etc/letsencrypt/live/dealsniffers.com/fullchain.pem ] || { echo "STOP: no certificate yet (run the certbot step first)"; exit 1; }
  systemctl is-active --quiet dealsniffer || { echo "STOP: the dealsniffer service is not running"; exit 1; }
fi
nginx -t >/dev/null 2>&1 || { echo "STOP: the CURRENT nginx configuration already fails nginx -t; not changing anything"; exit 1; }
if [ ! -d "$ACME" ]; then mkdir -p "$ACME"; : > "$ACME/.dealsniffer-managed"; chmod 755 "$ACME"; fi
prev=""; [ -f "$AV" ] && prev="$(mktemp)" && cp -p "$AV" "$prev"
install -m 644 "$SRC" "$AV"; ln -sfn "$AV" "$EN"
if nginx -t; then
  systemctl reload nginx; echo "nginx reloaded with the DealSniffer $1 site"
else
  if [ -n "$prev" ]; then cp -p "$prev" "$AV"; else rm -f "$EN" "$AV"; fi
  echo "STOP: nginx -t failed with the DealSniffer $1 site; it was removed/restored and nginx was NOT reloaded"; exit 1
fi
