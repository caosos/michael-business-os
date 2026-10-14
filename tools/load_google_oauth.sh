# shellcheck shell=bash
# Sourced by tools/reload_ui.sh when the DealSniffer UI starts. Loads Google sign-in settings at RUNTIME from protected host files;
# nothing is printed, logged or committed.
#   /etc/dealsniffer/google-oauth.env   owner's file: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET (root-owned; readable by this user's group)
#   ~/.config/mbos/google-session.env   MBOS_SESSION_SECRET (generated here once, mode 600), MBOS_GOOGLE_REDIRECT_URI, optional MBOS_OWNER_GOOGLE_EMAIL
#   ~/.config/mbos/google-oauth.env     older single-file form (tools/setup_google_oauth.sh), still honoured
# All-or-nothing: sign-in is switched on only when client ID, secret, redirect URI and session secret are all present, because the app
# refuses to start with a partial configuration and a missing value must not take the Marketplace down.
_ds_oauth_load() {
  local etc="${DS_OAUTH_ETC_FILE:-/etc/dealsniffer/google-oauth.env}" session="$HOME/.config/mbos/google-session.env" legacy="$HOME/.config/mbos/google-oauth.env"
  [ -r "$legacy" ] && { set -a; . "$legacy"; set +a; }
  if [ -r "$etc" ]; then
    local GOOGLE_CLIENT_ID="" GOOGLE_CLIENT_SECRET=""
    set -a; . "$etc"; set +a
    [ -n "$GOOGLE_CLIENT_ID" ] && export MBOS_GOOGLE_CLIENT_ID="$GOOGLE_CLIENT_ID"
    [ -n "$GOOGLE_CLIENT_SECRET" ] && export MBOS_GOOGLE_CLIENT_SECRET="$GOOGLE_CLIENT_SECRET"
    unset GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET
  fi
  if [ -n "${MBOS_GOOGLE_CLIENT_ID:-}" ] && [ ! -f "$session" ]; then
    ( umask 077; mkdir -p "$(dirname "$session")"
      printf 'MBOS_SESSION_SECRET=%s\nMBOS_GOOGLE_REDIRECT_URI=%s\n' \
        "$(head -c 48 /dev/urandom | base64 | tr -d '\n=+/')" "http://127.0.0.1:${PORT:-8766}/auth/google/callback" > "$session" )
  fi
  [ -r "$session" ] && { set -a; . "$session"; set +a; }
  if [ -z "${MBOS_GOOGLE_CLIENT_ID:-}" ] || [ -z "${MBOS_GOOGLE_CLIENT_SECRET:-}" ] || [ -z "${MBOS_GOOGLE_REDIRECT_URI:-}" ] || [ -z "${MBOS_SESSION_SECRET:-}" ]; then
    unset MBOS_GOOGLE_CLIENT_ID MBOS_GOOGLE_CLIENT_SECRET MBOS_GOOGLE_REDIRECT_URI MBOS_SESSION_SECRET MBOS_OWNER_GOOGLE_EMAIL
    echo "google sign-in: not configured (credentials incomplete or unreadable); the Marketplace runs in local owner mode" >&2
  else
    echo "google sign-in: configured from protected host files" >&2
  fi
}
_ds_oauth_load
unset -f _ds_oauth_load
