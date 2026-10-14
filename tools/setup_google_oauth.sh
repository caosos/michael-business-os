#!/usr/bin/env bash
# Google sign-in for DealSniffer on THIS machine, outside GitHub. The owner runs this himself after creating a Google OAuth
# "Web application" client whose Authorized redirect URI is exactly  http://127.0.0.1:8766/auth/google/callback
# It prompts for the client ID and (hidden) client secret, generates the session-signing secret locally, validates the set with
# the app's own loader, and writes ~/.config/mbos/google-oauth.env (mode 600). It never prints a secret. Agent 01 never sees them.
# tools/reload_ui.sh loads the file when the UI starts; the next release (or reload) turns sign-in on.
#   usage: tools/setup_google_oauth.sh            (prompts)
#          tools/setup_google_oauth.sh --check    (says whether the file exists, its mode, and which names are set; no values)
set -euo pipefail
cd "$(dirname "$0")/.."
dir="${HOME}/.config/mbos"
secret="${dir}/google-oauth.env"
redirect="http://127.0.0.1:8766/auth/google/callback"
names=(MBOS_GOOGLE_CLIENT_ID MBOS_GOOGLE_CLIENT_SECRET MBOS_GOOGLE_REDIRECT_URI MBOS_SESSION_SECRET)
if [ "${1:-}" = "--check" ]; then
  [ -f "$secret" ] || { echo "google sign-in file: absent (${secret})"; exit 1; }
  echo "google sign-in file: present, mode $(stat -c '%a' "$secret")"
  ok=0
  for n in "${names[@]}"; do
    if grep -q "^${n}=.\+" "$secret"; then echo "  ${n}: set"; else echo "  ${n}: MISSING"; ok=1; fi
  done
  grep -q "^MBOS_OWNER_GOOGLE_EMAIL=.\+" "$secret" && echo "  MBOS_OWNER_GOOGLE_EMAIL: set (owner login linked)" || echo "  MBOS_OWNER_GOOGLE_EMAIL: not set (Google login opens a separate account)"
  [ "$(stat -c '%a' "$secret")" = "600" ] && exit $ok || exit 1
fi
umask 077
mkdir -p "$dir"
chmod 700 "$dir"
echo "Google Cloud Console > APIs & Services > Credentials > your OAuth client (Web application)."
echo "Its Authorized redirect URI must be exactly: ${redirect}"
read -r -p "Client ID (ends in .apps.googleusercontent.com): " client_id
[[ "$client_id" =~ ^[A-Za-z0-9._-]+\.apps\.googleusercontent\.com$ ]] || { echo "That does not look like a Google OAuth client ID; nothing saved."; exit 2; }
read -r -s -p "Client secret (not shown while you type): " client_secret; echo
[ -n "$client_secret" ] && [[ "$client_secret" != *$'\n'* ]] || { echo "Empty client secret; nothing saved."; exit 2; }
read -r -p "Your own Google address, to open YOUR existing DealSniffer data when you sign in (Enter to skip): " owner_email
session_secret="$(head -c 48 /dev/urandom | base64 | tr -d '\n=+/')"
tmp="$(mktemp "${dir}/.google-oauth.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
printf 'MBOS_GOOGLE_CLIENT_ID=%s\nMBOS_GOOGLE_CLIENT_SECRET=%s\nMBOS_GOOGLE_REDIRECT_URI=%s\nMBOS_SESSION_SECRET=%s\n' \
  "$client_id" "$client_secret" "$redirect" "$session_secret" > "$tmp"
[ -z "$owner_email" ] || printf 'MBOS_OWNER_GOOGLE_EMAIL=%s\n' "$owner_email" >> "$tmp"
chmod 600 "$tmp"
# Validate with the app's own all-or-nothing loader before the live file is replaced (a bad file would stop the UI starting).
( set -a; . "$tmp"; set +a; PYTHONPATH="var/lanes/agent-06${PYTHONPATH:+:$PYTHONPATH}" .venv/bin/python -c \
  'from operator_ui import accounts; c = accounts.google_oauth_config(); assert c.enabled; o = accounts.owner_google_email(); print("validated: Google sign-in configuration is complete" + ("; your Google login opens the owner data" if o else ""))' ) \
  || { echo "The app rejected this configuration; nothing saved."; exit 2; }
mv "$tmp" "$secret"
trap - EXIT
echo "Saved to ${secret} (mode 600). Tell Agent 01 'oauth saved' so it can reload the UI and test sign-in."
