"""F-48: small composition fixes for the landing. Live-only mission header, honest bankroll label, free-form origin, GSA photo tile.
No network, no proxy, no token: GSA photo URLs (ppms.gov) answer 401 without a GSA login, so they are never loaded by the browser."""

from __future__ import annotations

import re
from html import escape as e

from . import live_demo

NO_PHOTO = "Photo is behind GSA's login: open the original listing"
BANKROLL = "Simulated bankroll, not your cash"
MAX_RADIUS = 25000
_LATLNG = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def live_only(loaded: dict, store) -> dict:
    """The loaded mission/plan without any demo or training item: legs, replace_if_stale and the cash ledger's recommendation basis."""
    doc = loaded.get("doc")
    if loaded.get("kind") != "plan" or not isinstance(doc, dict):
        return loaded
    legs = [l for l in doc.get("legs") or [] if not live_demo.is_demo(store.item(l.get("item_id")))]
    keep = [i for i in doc.get("replace_if_stale") or [] if not live_demo.is_demo(store.item(i))]
    return {**loaded, "doc": {**doc, "legs": legs, "replace_if_stale": keep}}


def bankroll_html(ledger: dict | None, money) -> str:
    """Labelled as simulated, with source and as-of. Never a recommendation: no 'deploy' wording and no action hangs off it."""
    avail = (ledger or {}).get("available_to_deploy")
    if avail is None:
        return "<b class='unk'>UNKNOWN</b> <span class='small mut'>no bankroll recorded; see <a href='/numbers'>My numbers</a></span>"
    src = e(str((ledger or {}).get("source") or "dry-run capital ledger (a simulation, no real money moves)"))
    asof = e(str((ledger or {}).get("as_of") or "UNKNOWN"))
    return (f"<b>{money(avail)}</b> <span class='lbl'>{BANKROLL}</span> <span class='small mut'>source: {src}; as of {asof}. "
            "Not used to recommend anything.</span>")


def parse_origin(base: str):
    """Any city or ZIP the user types is accepted. -> (lat, lng) when it can be located (explicit 'lat, lng', or a place lane 02 knows), else None."""
    m = _LATLNG.match(base or "")
    if m and abs(float(m.group(1))) <= 90 and abs(float(m.group(2))) <= 180:
        return float(m.group(1)), float(m.group(2))
    return None


def origin_note(base: str, located: bool, radius) -> str:
    """Said out loud when the typed origin cannot be located, instead of silently ignoring the radius."""
    if located:
        return ""
    return (f"<div class='card'><b>Origin '{e(base)}' accepted but not located.</b> Distances are UNKNOWN"
            + (f" and the {radius:g} mi radius is not applied" if radius is not None else "")
            + ". Type a city lane 02 knows (Arkansas towns), or 'latitude, longitude'.</div>")


def photo_tile(url, listing_url) -> str:
    """A GSA image (ppms.gov) cannot load without a GSA login (HTTP 401), so show a clean tile, never a broken <img>. The URL stays in details."""
    link = f" <a href='{e(listing_url)}' rel='noopener noreferrer' target='_blank'>open</a>" if listing_url else ""
    det = f"<details class='small mut'><summary>image URL</summary><code>{e(url)}</code></details>" if url else ""
    return f"<div class='mk-nophoto small mut' style='width:120px'>{e(NO_PHOTO)}{link}{det}</div>"


def is_gsa_image(url) -> bool:
    return bool(re.match(r"^https?://([^/]*\.)?ppms\.gov(/|$)", str(url or ""), re.I))
