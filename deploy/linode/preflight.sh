#!/usr/bin/env bash
# DealSniffer Linode preflight: READ-ONLY. Changes nothing (no installs, no files, no services, no nginx reload).
# Run from the repo checkout:   bash deploy/linode/preflight.sh
# Prints PASS / WARN / FAIL lines and a final verdict; paste the output back to Agent 01.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
. "$HERE/components.env"
fail=0; warn=0
pass() { printf 'PASS  %s\n' "$*"; }
wn()   { printf 'WARN  %s\n' "$*"; warn=$((warn+1)); }
bad()  { printf 'FAIL  %s\n' "$*"; fail=$((fail+1)); }

echo "== host"
. /etc/os-release 2>/dev/null; echo "os: ${PRETTY_NAME:-unknown}; kernel $(uname -r); arch $(uname -m); user $(id -un)"
[ "$(uname -m)" = x86_64 ] && pass "architecture x86_64 (the wheel lock is for x86_64)" || bad "architecture $(uname -m): the wheel lock is x86_64 only"
PY=$(command -v "python${PYTHON_MINOR}" || true)
[ -n "$PY" ] && pass "python ${PYTHON_MINOR}: $($PY --version 2>&1)" || bad "python${PYTHON_MINOR} not found"
if [ -n "$PY" ]; then
  tmp=$(mktemp -d); if "$PY" -m venv "$tmp/v" >/dev/null 2>&1 && [ -x "$tmp/v/bin/pip" ]; then pass "python venv + pip work"; else bad "python venv/ensurepip missing (prerequisite: the Ubuntu package python${PYTHON_MINOR}-venv)"; fi; rm -rf "$tmp"
fi
command -v git >/dev/null && pass "git $(git --version | cut -d' ' -f3)" || bad "git missing"
command -v nginx >/dev/null && pass "nginx present" || bad "nginx missing"
systemctl is-active --quiet nginx && pass "nginx active" || bad "nginx not active"
command -v certbot >/dev/null && pass "certbot $(certbot --version 2>&1 | awk '{print $2}')" || bad "certbot missing"
command -v curl >/dev/null && pass "curl present" || bad "curl missing"
command -v systemctl >/dev/null && pass "systemd present" || bad "systemd missing"
df -BG --output=avail / | tail -1 | awk '{g=$1+0; exit !(g>=3)}' && pass "disk: $(df -h --output=avail / | tail -1 | tr -d ' ') free on /" || bad "less than 3 GB free on /"
awk '/MemAvailable/{exit !($2>=400000)}' /proc/meminfo && pass "memory: $(awk '/MemAvailable/{printf "%.1f GiB", $2/1048576}' /proc/meminfo) available" || wn "less than ~400 MB RAM available"

echo "== repository"
git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 && pass "repo: $REPO" || bad "not a git checkout: $REPO"
echo "checked-out commit: $(git -C "$REPO" rev-parse HEAD 2>/dev/null)"
for v in UI_SHA MBOS_SHA DISCOVERY_SHA ECONOMICS_SHA; do
  sha="${!v}"; git -C "$REPO" cat-file -e "${sha}^{commit}" 2>/dev/null && pass "$v ${sha:0:12} present" || bad "$v ${sha:0:12} missing (run: git -C $REPO fetch origin)"
done

echo "== must not collide with existing apps"
if ss -ltnH "sport = :${PORT}" 2>/dev/null | grep -q .; then bad "port ${PORT} is already in use: $(ss -ltnpH "sport = :${PORT}" 2>/dev/null | head -1)"; else pass "port ${PORT} free"; fi
for p in 3000 8000 8001 27017 80 443; do ss -ltnH "sport = :$p" 2>/dev/null | grep -q . && echo "info: existing listener on :$p (left alone)"; done
id dealsniffer >/dev/null 2>&1 && wn "user 'dealsniffer' already exists (install will refuse unless it is DealSniffer-managed)" || pass "user 'dealsniffer' does not exist yet"
for p in /opt/dealsniffer /var/lib/dealsniffer /etc/dealsniffer /etc/systemd/system/dealsniffer.service /etc/nginx/sites-available/dealsniffers.com /etc/nginx/sites-enabled/dealsniffers.com /var/www/dealsniffer-acme; do
  if [ -e "$p" ]; then
    if [ -e "$p/.dealsniffer-managed" ] || grep -qs "DealSniffer-managed" "$p" 2>/dev/null; then pass "$p exists and is DealSniffer-managed"; else wn "$p already exists and is NOT DealSniffer-managed (install will stop rather than overwrite it)"; fi
  else pass "$p absent"; fi
done
if sudo -n true 2>/dev/null; then
  NGX=$(sudo -n nginx -T 2>/dev/null || true)
  echo "$NGX" | grep -qiE "server_name[^;]*dealsniffers\.com" && wn "an existing nginx server block already names dealsniffers.com (list: $(echo "$NGX" | grep -n '# configuration file' | wc -l) files); show with: sudo nginx -T | grep -n -B3 -A3 dealsniffers" || pass "no existing nginx server block for dealsniffers.com"
  sudo -n nginx -t >/dev/null 2>&1 && pass "current nginx configuration tests OK" || bad "current nginx configuration does not pass nginx -t (fix before adding a site)"
  [ -d /etc/letsencrypt/live/dealsniffers.com ] && echo "info: a certificate for dealsniffers.com already exists" || echo "info: no certificate for dealsniffers.com yet"
  sudo -n test -d /etc/nginx/sites-enabled && pass "nginx uses sites-available/sites-enabled" || wn "no /etc/nginx/sites-enabled (layout differs; tell Agent 01)"
else
  wn "sudo needs a password; nginx/certificate checks skipped. Re-run as: sudo -v && bash deploy/linode/preflight.sh"
fi

echo "== DNS (from this host)"
for h in dealsniffers.com www.dealsniffers.com; do echo "$h -> $(getent ahostsv4 $h | awk '{print $1}' | sort -u | tr '\n' ' ')"; done
echo "this host public IPv4 candidates: $(hostname -I 2>/dev/null)"

echo "== verdict: $fail FAIL, $warn WARN"
[ "$fail" -eq 0 ] && echo "PREFLIGHT OK" || echo "PREFLIGHT NOT OK"
