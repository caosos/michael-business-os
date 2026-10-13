#!/usr/bin/env bash
# B-12 / B-27: install the alerts-mailbox secret for DealSniffer on THIS machine, outside GitHub.
# The owner runs this himself; it prompts for the Gmail app password without echoing it, writes it to a mode-0600 file under
# ~/.config/mbos/, and never prints it. Agent 01 never sees the value. No mail is read by this script.
#   usage: tools/setup_alerts_mailbox.sh            (prompts)
#          tools/setup_alerts_mailbox.sh --check    (says whether the secret file exists and has mode 600; prints no secret)
set -euo pipefail
dir="${HOME}/.config/mbos"
secret="${dir}/imap.env"
if [ "${1:-}" = "--check" ]; then
  if [ -f "$secret" ]; then
    mode=$(stat -c '%a' "$secret")
    grep -q '^MBOS_IMAP_PASSWORD=.\+' "$secret" && filled=yes || filled=no
    echo "secret file: present, mode ${mode}, password set: ${filled}"
    [ "$mode" = "600" ] && [ "$filled" = yes ]
  else
    echo "secret file: absent (${secret})"; exit 1
  fi
  exit $?
fi
umask 077
mkdir -p "$dir"
chmod 700 "$dir"
echo "Paste the 16-character Gmail APP PASSWORD (Google Account > Security > 2-Step Verification > App passwords)."
echo "It is not shown while you type and is saved only to ${secret} (mode 600)."
IFS= read -r -s -p "App password: " pw; echo
pw="${pw// /}"                       # Google shows it in groups of four; spaces are not part of it
if [ "${#pw}" -lt 12 ]; then echo "That looks too short for an app password; nothing was saved." >&2; exit 2; fi
tmp=$(mktemp "${dir}/.imap.env.XXXXXX")
printf 'MBOS_IMAP_PASSWORD=%s\n' "$pw" > "$tmp"
chmod 600 "$tmp"
mv -f "$tmp" "$secret"
unset pw
echo "Saved. Check: tools/setup_alerts_mailbox.sh --check"
