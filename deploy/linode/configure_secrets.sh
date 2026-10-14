#!/usr/bin/env bash
# DealSniffer Google sign-in secrets for the PUBLIC site. Michael runs this himself on the server; nothing is echoed, logged or committed.
#   sudo bash deploy/linode/configure_secrets.sh            (prompts; refuses to replace an existing file)
#   sudo bash deploy/linode/configure_secrets.sh --replace  (deliberately replace it)
#   sudo bash deploy/linode/configure_secrets.sh --check    (names, mode and owner only; no values)
# Writes /etc/dealsniffer/oauth.env (root:dealsniffer, mode 640): MBOS_GOOGLE_CLIENT_ID, MBOS_GOOGLE_CLIENT_SECRET, MBOS_SESSION_SECRET
# (generated here), optional MBOS_OWNER_GOOGLE_EMAIL. The redirect URI is fixed in dealsniffer.env:
#   https://dealsniffers.com/auth/google/callback  (must be listed exactly in the Google OAuth client's Authorized redirect URIs)
set -euo pipefail
R="${DS_ROOT:-}"; CONF="$R/etc/dealsniffer"; F="$CONF/oauth.env"; VENV="$R/opt/dealsniffer/current/venv"
[ -n "${DS_TEST:-}" ] || [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
if [ "${1:-}" = "--check" ]; then
  [ -f "$F" ] || { echo "oauth.env: absent"; exit 1; }
  echo "oauth.env: $(stat -c 'mode %a owner %U:%G' "$F")"
  for n in MBOS_GOOGLE_CLIENT_ID MBOS_GOOGLE_CLIENT_SECRET MBOS_SESSION_SECRET MBOS_OWNER_GOOGLE_EMAIL; do
    grep -q "^$n=.\+" "$F" && echo "  $n: set" || echo "  $n: not set"; done
  exit 0
fi
[ -d "$CONF" ] && [ -e "$CONF/.dealsniffer-managed" ] || { echo "STOP: $CONF missing; run install.sh first"; exit 1; }
[ -x "$VENV/bin/python" ] || { echo "STOP: no installed release venv; run install.sh first"; exit 1; }
if [ -e "$F" ] && [ "${1:-}" != "--replace" ]; then echo "STOP: $F already exists; use --replace to change it deliberately"; exit 1; fi
echo "Google Cloud Console > APIs & Services > Credentials > your Web application client."
echo "Its Authorized redirect URIs must include exactly: https://dealsniffers.com/auth/google/callback"
read -r -p "Client ID (ends in .apps.googleusercontent.com): " cid
[[ "$cid" =~ ^[A-Za-z0-9._-]+\.apps\.googleusercontent\.com$ ]] || { echo "Not a Google OAuth client ID; nothing saved."; exit 2; }
read -r -s -p "Client secret (hidden): " csec; echo
[[ -n "$csec" && "$csec" != *[[:space:]]* ]] || { echo "Empty or contains spaces; nothing saved."; exit 2; }
read -r -p "Your own Google address to link to the site owner (Enter to skip; can be added later): " owner
sess="$(head -c 48 /dev/urandom | base64 | tr -d '\n=+/')"
tmp="$(mktemp "$CONF/.oauth.XXXXXX")"; trap 'rm -f "$tmp"' EXIT
{ echo "# DealSniffer-managed. Secrets for Google sign-in; never print or commit."
  printf 'MBOS_GOOGLE_CLIENT_ID=%s\nMBOS_GOOGLE_CLIENT_SECRET=%s\nMBOS_SESSION_SECRET=%s\n' "$cid" "$csec" "$sess"
  [ -z "$owner" ] || printf 'MBOS_OWNER_GOOGLE_EMAIL=%s\n' "$owner"; } > "$tmp"
chmod 640 "$tmp"; [ -n "${DS_TEST:-}" ] || chown root:dealsniffer "$tmp"
( set -a; . "$CONF/dealsniffer.env"; . "$tmp"; set +a
  PYTHONPATH="$R/opt/dealsniffer/current" "$VENV/bin/python" -c '
from operator_ui import accounts
c = accounts.google_oauth_config(); accounts.owner_google_email()
assert c.enabled and c.redirect_uri == "https://dealsniffers.com/auth/google/callback"
print("validated by the app: Google sign-in settings are complete; redirect", c.redirect_uri)' ) || { echo "The app rejected these settings; nothing saved."; exit 2; }
mv "$tmp" "$F"; trap - EXIT
echo "Saved $F ($(stat -c 'mode %a owner %U:%G' "$F")). Values were not shown."
