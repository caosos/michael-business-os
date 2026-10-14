# DealSniffer on the Linode (dealsniffers.com) — limited owner/test deployment

The EliteDesk stays the development host. This package installs ONE pinned, isolated public site on Michael's existing Linode without
touching CAOSCare, Cutler Lawns, their databases, services or nginx blocks. It is a **limited owner/test deployment**, not production:
multi-user persistence, backups and recovery are not yet proven (see "Not yet proven").

## What gets installed

| Piece | Where | Owner / mode |
|---|---|---|
| Code, one directory per pinned release | `/opt/dealsniffer/releases/<id>`; active one = symlink `/opt/dealsniffer/current` | root, read-only |
| Python venv per hash lock | `/opt/dealsniffer/venvs/lock-<hash>` (the release links it as `venv`) | root, read-only |
| Data (accounts, preferences, bids, caches) | `/var/lib/dealsniffer` (each release's `var` links here) | `dealsniffer`, 750/700 |
| Settings | `/etc/dealsniffer/dealsniffer.env` (no secrets) | root:dealsniffer 640 |
| Google sign-in secrets | `/etc/dealsniffer/oauth.env` (entered by Michael with `configure_secrets.sh`) | root:dealsniffer 640 |
| Service | `dealsniffer.service`, user `dealsniffer` (system, no shell), `127.0.0.1:8765` only, hardened | systemd |
| Logs | `journalctl -u dealsniffer` | journald |
| nginx | only `sites-available/dealsniffers.com` + its `sites-enabled` link; ACME webroot `/var/www/dealsniffer-acme` | root |

Every path above carries a `DealSniffer-managed` marker. Any of them that already exists WITHOUT the marker stops the install before
anything is created. Nothing is downloaded except the 22 pinned, hash-checked wheels from PyPI (`requirements.lock`,
`build-requirements.lock`); the four in-house components come from exact commits (`components.env`) via `git archive`.

Public mode (`MBOS_PUBLIC_DEPLOYMENT=1`): no database and no development spine; there is no local owner, loopback/unknown Host headers get
403, customer pages need Google sign-in, operator pages stay closed even when signed in, saved searches are off. Paid providers are denied
in code (`PAID_PROVIDER_REQUESTS = "DENIED"`). Nothing refreshes listings automatically; the Marketplace starts empty/offline.

## Prerequisites (checked by `preflight.sh`)
Ubuntu with `python3.12` and its venv module (`python3.12-venv`), git, nginx (sites-available layout), certbot, curl, systemd, x86_64,
port 8765 free, ≥3 GB disk, DNS for dealsniffers.com and www → this host. Google OAuth client (Web application) whose Authorized redirect
URIs include exactly `https://dealsniffers.com/auth/google/callback`.

## Order (each step only after the previous one reported OK)
1. `bash deploy/linode/preflight.sh` — read-only.
2. `sudo bash deploy/linode/install.sh` — user, directories, release, venv, settings, unit (not started). Idempotent.
3. `sudo bash deploy/linode/configure_secrets.sh` — Michael types the Google client ID and secret privately.
4. `sudo systemctl enable --now dealsniffer && bash deploy/linode/verify.sh` — backend checks.
5. `sudo bash deploy/linode/nginx_site.sh acme` — port-80 challenge-only site (tests `nginx -t`, reverts itself on failure).
6. `sudo certbot certonly --webroot -w /var/www/dealsniffer-acme -d dealsniffers.com -d www.dealsniffers.com --deploy-hook "systemctl reload nginx"`
   — does not edit any nginx file.
7. `sudo bash deploy/linode/nginx_site.sh https && bash deploy/linode/verify.sh --public` — HTTPS site and public checks.
8. Google sign-in tried in a browser at https://dealsniffers.com/home.

## Rollback (data and secrets are never deleted)
* Take the site off nginx: `sudo bash deploy/linode/rollback.sh site`
* Stop the app: `sudo bash deploy/linode/rollback.sh stop`
* Previous release: `sudo bash deploy/linode/rollback.sh previous`
* Undo phase 1 only: same as `site`. Certificates stay in `/etc/letsencrypt` (harmless; `sudo certbot delete --cert-name dealsniffers.com` removes them).

## Uninstall (manual, deliberate)
`rollback.sh site` and `rollback.sh stop`, then `sudo rm /etc/systemd/system/dealsniffer.service /etc/nginx/sites-available/dealsniffers.com
&& sudo systemctl daemon-reload`. `/opt/dealsniffer`, `/var/lib/dealsniffer` (customer data) and `/etc/dealsniffer` (secrets) are removed
only by hand after a backup decision.

## Tested on the EliteDesk (test mode, scratch root, no root privileges)
Pinned install from exact commits and hash-locked wheels; idempotent re-run; refusal on a foreign path before any change; secrets script
(validation by the app, no overwrite without `--replace`); app started exactly as the unit does; `verify.sh` backend checks 17/17; no
file fetched into the data directory; `rollback.sh previous`; unit file accepted by `systemd-analyze verify`.

## Not tested here (first exercised on the Linode, each guarded)
Real `useradd`/`chown`/`systemctl` (root), the hardened unit under systemd, `nginx -t` of the two site files (no nginx on the EliteDesk;
`nginx_site.sh` reverts itself if the test fails), certbot issuance, the public HTTPS checks and a real Google sign-in.

## Not yet proven (before calling this production or multi-user)
Backups and restore of `/var/lib/dealsniffer`; recovery after host loss; per-account persistence under concurrent users; saved searches
per account; listing sources on the Linode (none refresh yet; GSA would need its own free key and an explicit refresh decision).
