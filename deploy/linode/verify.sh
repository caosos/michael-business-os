#!/usr/bin/env bash
# DealSniffer verification: READ-ONLY HTTP checks. Changes nothing.
#   bash deploy/linode/verify.sh                         backend checks on 127.0.0.1:8765 (as nginx would call it)
#   bash deploy/linode/verify.sh --public                also the public https://dealsniffers.com checks (after nginx + certificate)
#   DS_BACKEND=http://127.0.0.1:8797 bash verify.sh      another backend (tests)
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/components.env"
B="${DS_BACKEND:-http://127.0.0.1:$PORT}"; H=dealsniffers.com; CB="https://dealsniffers.com/auth/google/callback"
fail=0
ok()  { printf 'PASS  %s\n' "$*"; }
no()  { printf 'FAIL  %s\n' "$*"; fail=$((fail+1)); }
code() { curl -s -o /dev/null -w '%{http_code}' -m 10 "$@"; }
hdr()  { curl -s -D - -o /dev/null -m 10 "$@" | tr -d '\r'; }
body() { curl -s -m 10 "$@"; }

echo "== backend $B (Host: $H)"
for p in /home /privacy /terms; do c=$(code -H "Host: $H" "$B$p"); [ "$c" = 200 ] && ok "$p 200" || no "$p returned $c"; done
body -H "Host: $H" "$B/home" | grep -q "Continue with Google" && ok "/home offers Google sign-in" || no "/home has no Google sign-in button (secrets missing?)"
loc=$(hdr -H "Host: $H" "$B/market" | awk 'tolower($1)=="location:"{print $2}'); [[ "$loc" == /home?next=* ]] && ok "/market signed-out -> sign-in" || no "/market signed-out did not redirect to sign-in ($loc)"
for p in /queue /numbers /inputs /mission; do c=$(code -H "Host: $H" "$B$p"); [[ "$c" =~ ^(303|404)$ ]] && ok "operator $p closed ($c)" || no "operator $p returned $c"; done
for h in 127.0.0.1 localhost "[::1]" www.dealsniffers.com evil.example; do c=$(code -H "Host: $h" "$B/market"); [ "$c" = 403 ] && ok "Host $h rejected (403): no local-owner mode" || no "Host $h returned $c"; done
start=$(hdr -H "Host: $H" "$B/auth/google/start" | awk 'tolower($1)=="location:"{print $2}')
[[ "$start" == https://accounts.google.com/o/oauth2/v2/auth?* ]] && ok "/auth/google/start -> Google" || no "/auth/google/start did not redirect to Google"
python3 - "$start" "$CB" <<'PY' && ok "redirect_uri is exactly $CB; scopes openid email profile" || no "redirect_uri/scope mismatch"
import sys; from urllib.parse import urlparse, parse_qs
q = parse_qs(urlparse(sys.argv[1]).query); sys.exit(0 if q.get("redirect_uri") == [sys.argv[2]] and q.get("scope") == ["openid email profile"] else 1)
PY
if command -v ss >/dev/null; then
  l=$(ss -ltnH "sport = :${B##*:}" | awk '{print $4}' | sort -u | tr '\n' ' ')
  [[ -n "$l" && ! "$l" =~ (0\.0\.0\.0|\*|\[::\]): ]] && ok "backend listens on loopback only ($l)" || no "backend listener not loopback-only: ${l:-none}"
fi

if [ "${1:-}" = "--public" ]; then
  echo "== public https://$H"
  for p in /home /privacy /terms; do c=$(code "https://$H$p"); [ "$c" = 200 ] && ok "https $p 200" || no "https $p returned $c"; done
  c=$(code "http://$H/home"); l=$(hdr "http://$H/home" | awk 'tolower($1)=="location:"{print $2}'); [[ "$c" = 301 && "$l" == https://$H/home ]] && ok "http -> https (301)" || no "http not redirected to https ($c $l)"
  l=$(hdr "https://www.$H/home" | awk 'tolower($1)=="location:"{print $2}'); [[ "$l" == https://$H/home ]] && ok "www -> apex" || no "www did not redirect to apex ($l)"
  echo | openssl s_client -connect "$H:443" -servername "$H" 2>/dev/null | openssl x509 -noout -checkend 604800 >/dev/null && ok "certificate valid for 7+ days" || no "certificate missing or expiring"
  ps=$(hdr "https://$H/auth/google/start" | awk 'tolower($1)=="location:"{print $2}'); python3 - "$ps" "$CB" <<'PY' && ok "public sign-in uses $CB" || no "public sign-in redirect mismatch"
import sys; from urllib.parse import urlparse, parse_qs
sys.exit(0 if parse_qs(urlparse(sys.argv[1]).query).get("redirect_uri") == [sys.argv[2]] else 1)
PY
  c=$(code "https://$H/queue"); [[ "$c" =~ ^(303|404)$ ]] && ok "public /queue closed ($c)" || no "public /queue returned $c"
  c=$(code -m 5 "http://172.234.25.199:$PORT/home" 2>/dev/null); [ "$c" = 000 ] && ok "backend port $PORT not reachable from outside" || no "backend port $PORT answered from the public IP ($c)"
fi
echo "== $fail FAIL"; [ "$fail" -eq 0 ] && echo "VERIFY OK" || echo "VERIFY NOT OK"
[ "$fail" -eq 0 ]
