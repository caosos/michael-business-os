#!/usr/bin/env bash
# Craigslist / GovDeals / Public Surplus ALERT E-MAILS for the public site: the dedicated alerts mailbox, read-only. Michael runs this himself;
# the Gmail APP PASSWORD (16 letters, Google Account > Security > App passwords; never the normal password) is typed hidden and never shown.
#   sudo bash deploy/linode/configure_alerts.sh            (refuses to replace an existing file)
#   sudo bash deploy/linode/configure_alerts.sh --replace
# Writes /etc/dealsniffer/alerts.env (root:dealsniffer 640). The hourly refresh then reads the mailbox once an hour.
set -euo pipefail
F=/etc/dealsniffer/alerts.env
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
[ -e /etc/dealsniffer/.dealsniffer-managed ] || { echo "STOP: run install.sh first"; exit 1; }
if [ -e "$F" ] && [ "${1:-}" != "--replace" ]; then echo "STOP: $F exists; use --replace"; exit 1; fi
read -r -p "Alerts mailbox [dealsniffer2026@gmail.com]: " user; user="${user:-dealsniffer2026@gmail.com}"
[[ "$user" == *@* && "$user" != *[[:space:]]* ]] || { echo "Not an e-mail address; nothing saved."; exit 2; }
read -r -s -p "Gmail app password for $user (hidden): " pw; echo
pw="${pw// /}"; [[ "$pw" =~ ^[A-Za-z]{16}$ ]] || { echo "An app password is 16 letters; nothing saved."; exit 2; }
tmp="$(mktemp /etc/dealsniffer/.alerts.XXXXXX)"; trap 'rm -f "$tmp"' EXIT
printf '# DealSniffer-managed. Read-only alerts mailbox; never print.\nMBOS_ALERT_IMAP_HOST=imap.gmail.com\nMBOS_ALERT_IMAP_USER=%s\nMBOS_IMAP_PASSWORD=%s\nMBOS_ALERT_IMAP_FOLDER=INBOX\n' "$user" "$pw" > "$tmp"
chmod 640 "$tmp"; chown root:dealsniffer "$tmp"; mv "$tmp" "$F"; trap - EXIT
echo "Saved $F ($(stat -c 'mode %a owner %U:%G' "$F")). The next hourly refresh reads $user (read-only)."
