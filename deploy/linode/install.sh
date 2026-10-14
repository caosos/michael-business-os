#!/usr/bin/env bash
# DealSniffer Linode install: builds ONE pinned release and its venv, creates the unprivileged service user, private config and data
# directories, and installs (but does NOT start) the systemd unit. It never touches nginx, certificates, other apps or their data,
# never fetches a moving branch, never refreshes a listing source and never contacts a paid provider.
#   sudo bash deploy/linode/install.sh
# Refuses to overwrite: any path that exists without the DealSniffer marker stops the install. Re-running with the same pins reuses the
# finished release/venv (idempotent). Test mode for CI/dev (no root): DS_TEST=1 DS_ROOT=/tmp/x bash install.sh  (all paths under DS_ROOT,
# no user, no chown, no systemd).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
. "$HERE/components.env"
TEST="${DS_TEST:-0}"; R="${DS_ROOT:-}"
OPT="$R/opt/dealsniffer"; DATA="$R/var/lib/dealsniffer"; CONF="$R/etc/dealsniffer"; UNIT="$R/etc/systemd/system/dealsniffer.service"
MARK=".dealsniffer-managed"; SVC=dealsniffer
PY="${DS_PYTHON:-$(command -v "python${PYTHON_MINOR}" || true)}"
die() { echo "STOP: $*" >&2; exit 1; }
say() { echo "== $*"; }

[ "$TEST" = 1 ] || [ "$(id -u)" = 0 ] || die "run with sudo (or DS_TEST=1 DS_ROOT=... for a dry build)"
[ "$TEST" = 1 ] || [ -z "$R" ] || die "DS_ROOT is only for test mode"
[ -n "$PY" ] || die "python${PYTHON_MINOR} not found"
for v in UI_SHA MBOS_SHA DISCOVERY_SHA ECONOMICS_SHA; do git -C "$REPO" cat-file -e "${!v}^{commit}" 2>/dev/null || die "$v ${!v} not in $REPO (git fetch origin)"; done
LOCKHASH=$(cat "$HERE/requirements.lock" "$HERE/build-requirements.lock" | sha256sum | cut -c1-12)
REL_ID="ui-${UI_SHA:0:12}_mbos-${MBOS_SHA:0:12}_disc-${DISCOVERY_SHA:0:12}_econ-${ECONOMICS_SHA:0:12}_lock-${LOCKHASH}"
REL="$OPT/releases/$REL_ID"; VENV="$OPT/venvs/lock-$LOCKHASH"

# A path we create gets the marker; a path that exists without it belongs to someone else and is never touched.
claim_dir() {  # path mode owner group
  local p="$1"
  if [ -e "$p" ] && [ ! -e "$p/$MARK" ]; then die "$p exists and is not DealSniffer-managed; refusing to touch it"; fi
  mkdir -p "$p"; : > "$p/$MARK"; chmod "$2" "$p"
  [ "$TEST" = 1 ] || chown "$3:$4" "$p"
}
check_file_free() { [ ! -e "$1" ] || grep -qs "DealSniffer-managed" "$1" || die "$1 exists and is not DealSniffer-managed"; }

say "ownership check (nothing is created until every path is clear)"
for p in "$OPT" "$OPT/releases" "$OPT/venvs" "$DATA" "$DATA/cache" "$DATA/accounts" "$CONF"; do
  [ ! -e "$p" ] || [ -e "$p/$MARK" ] || die "$p exists and is not DealSniffer-managed; nothing was changed"
done
for f in "$CONF/dealsniffer.env" "$UNIT"; do check_file_free "$f"; done
if [ "$TEST" != 1 ] && id "$SVC" >/dev/null 2>&1 && [ "$(getent passwd "$SVC" | cut -d: -f6)" != /var/lib/dealsniffer ]; then
  die "user $SVC exists with another home; nothing was changed"; fi
echo "all target paths are free or DealSniffer-managed"

say "service user"
if [ "$TEST" != 1 ]; then
  if id "$SVC" >/dev/null 2>&1; then
    [ "$(getent passwd "$SVC" | cut -d: -f6)" = /var/lib/dealsniffer ] || die "user $SVC exists with another home; refusing"
    echo "user $SVC already present (DealSniffer home)"
  else
    useradd --system --user-group --home-dir /var/lib/dealsniffer --no-create-home --shell /usr/sbin/nologin --comment "DealSniffer public site" "$SVC"
    echo "created system user $SVC (no login shell, no password)"
  fi
fi

say "directories"
claim_dir "$OPT" 755 root root; claim_dir "$OPT/releases" 755 root root; claim_dir "$OPT/venvs" 755 root root
claim_dir "$DATA" 750 "$SVC" "$SVC"; claim_dir "$DATA/cache" 750 "$SVC" "$SVC"; claim_dir "$DATA/accounts" 700 "$SVC" "$SVC"
claim_dir "$CONF" 750 root "$SVC"

say "release $REL_ID"
if [ -f "$REL/BUILD_INFO" ]; then echo "release already built (reused)"; else
  [ ! -e "$REL" ] || die "$REL exists but is incomplete (no BUILD_INFO); move it aside and re-run"
  stage="$(mktemp -d "$OPT/releases/.stage-XXXXXX")"
  git -C "$REPO" archive "$UI_SHA" operator_ui comms_spec | tar -x -C "$stage"
  ln -s "$( [ "$TEST" = 1 ] && echo "$DATA" || echo /var/lib/dealsniffer )" "$stage/var"   # every repo-relative var/ default lands in the persistent data dir
  ln -s "$VENV" "$stage/venv"                                               # the release names its own pinned venv
  printf 'release=%s\nui=%s\nmbos=%s\ndiscovery=%s\neconomics=%s\nlock=%s\nbuilt_utc=%s\n' "$REL_ID" "$UI_SHA" "$MBOS_SHA" "$DISCOVERY_SHA" "$ECONOMICS_SHA" "$LOCKHASH" "$(date -u +%FT%TZ)" > "$stage/BUILD_INFO"
  chmod -R a+rX,go-w "$stage"; mv "$stage" "$REL"; echo "release built"
fi

say "venv lock-$LOCKHASH"
if [ -f "$VENV/.complete" ]; then echo "venv already built (reused)"; else
  [ ! -e "$VENV" ] || die "$VENV exists but is incomplete; move it aside and re-run"
  vstage="$OPT/venvs/.stage-lock-$LOCKHASH"; rm -rf "$vstage"
  "$PY" -m venv "$vstage"
  src="$(mktemp -d)"; trap 'rm -rf "$src"' EXIT
  mkdir -p "$src/mbos" "$src/disc" "$src/econ"
  git -C "$REPO" archive "$MBOS_SHA" pyproject.toml setup.py src config docs/research/contracts | tar -x -C "$src/mbos"
  git -C "$REPO" archive "$DISCOVERY_SHA" pyproject.toml src | tar -x -C "$src/disc"
  git -C "$REPO" archive "$ECONOMICS_SHA" economics | tar -x -C "$src/econ"
  P="$vstage/bin/pip"
  "$P" install --quiet --no-input --disable-pip-version-check --require-hashes --no-deps -r "$HERE/build-requirements.lock"
  "$P" install --quiet --no-input --disable-pip-version-check --require-hashes --no-deps -r "$HERE/requirements.lock"
  "$P" install --quiet --no-input --disable-pip-version-check --no-deps --no-build-isolation "$src/mbos" "$src/disc" "$src/econ/economics"
  "$P" check >/dev/null || { "$P" check; die "dependency check failed"; }
  touch "$vstage/.complete"; chmod -R a+rX,go-w "$vstage"; mv "$vstage" "$VENV"; echo "venv built"
fi
[ "$(readlink "$REL/venv")" = "$VENV" ] || die "$REL/venv does not point at $VENV"

say "import check (public mode, as the service user)"
RUN=(env -i PATH=/usr/bin:/bin HOME="$DATA" PYTHONPATH="$REL" MBOS_PUBLIC_DEPLOYMENT=1 "$VENV/bin/python" -I -c
     "import sys; sys.path.insert(0, '$REL'); import operator_ui.server, operator_ui.public_store, operator_ui.market_facebook as fb; assert fb.PAID_PROVIDER_REQUESTS == 'DENIED'; print('imports OK; paid providers', fb.PAID_PROVIDER_REQUESTS)")
if [ "$TEST" = 1 ]; then "${RUN[@]}"; else runuser -u "$SVC" -- "${RUN[@]}"; fi

say "configuration (non-secret)"
ENVF="$CONF/dealsniffer.env"; check_file_free "$ENVF"
[ -f "$ENVF" ] && echo "kept existing $ENVF" || {
  cat > "$ENVF" <<EOF
# DealSniffer-managed. Non-secret settings for the public site. Secrets live in oauth.env (written by configure_secrets.sh).
MBOS_PUBLIC_DEPLOYMENT=1
MBOS_GOOGLE_REDIRECT_URI=https://dealsniffers.com/auth/google/callback
MBOS_ACCOUNT_DATA_DIR=/var/lib/dealsniffer/accounts
MBOS_GSA_CACHE=/var/lib/dealsniffer/cache/gsa-active-auctions.json
MBOS_FACEBOOK_CACHE=/var/lib/dealsniffer/cache/facebook-marketplace.json
MBOS_MARKET_PREFS_FILE=/var/lib/dealsniffer/owner-prefs-unused.json
PYTHONDONTWRITEBYTECODE=1
EOF
  chmod 640 "$ENVF"; [ "$TEST" = 1 ] || chown root:"$SVC" "$ENVF"; echo "wrote $ENVF"; }

say "systemd unit (installed, NOT started)"
check_file_free "$UNIT"; mkdir -p "$(dirname "$UNIT")"
sed -e "s|@PORT@|$PORT|g" "$HERE/dealsniffer.service" > "$UNIT.tmp" && mv "$UNIT.tmp" "$UNIT"; chmod 644 "$UNIT"
if [ "$TEST" != 1 ]; then systemctl daemon-reload; fi
echo "unit at $UNIT"

say "activate release (symlink only)"
CUR="$OPT/current"
if [ -L "$CUR" ] && [ "$(readlink "$CUR")" != "$REL" ]; then ln -sfn "$(readlink "$CUR")" "$OPT/previous"; echo "previous -> $(readlink "$OPT/previous")"; fi
ln -sfn "$REL" "$CUR.tmp" && mv -Tf "$CUR.tmp" "$CUR"; echo "current -> $REL"
echo "INSTALL OK: release $REL_ID, venv lock-$LOCKHASH. Next: configure_secrets.sh (Google sign-in), then start the service."
