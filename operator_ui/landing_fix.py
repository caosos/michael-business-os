"""F-48: small composition fixes for the landing. Live-only mission header, honest bankroll label, free-form origin, GSA photo tile.
No network, no proxy, no token: GSA photo URLs (ppms.gov) answer 401 without a GSA login, so they are never loaded by the browser."""

from __future__ import annotations

import os
import re
from html import escape as e

from . import gazetteer, live_demo

NO_PHOTO = "Photo is behind GSA's login: open the original listing"
BANKROLL = "Simulated bankroll, not your cash"
MAX_RADIUS = 25000
_LATLNG = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def live_only(loaded: dict, store) -> dict:
    """The loaded mission/plan without any demo or training item: legs, replace_if_stale and the cash ledger's recommendation basis."""
    doc = loaded.get("doc")
    if loaded.get("kind") != "plan" or not isinstance(doc, dict):
        return loaded
    def demo(iid):  # an id the store does not know cannot be shown as real (F-48), and a TRAIN-* id is demo by name
        it = store.item(iid)
        return it is None or str(iid).upper().startswith("TRAIN-") or LiveStore._demo(it)

    legs = [l for l in doc.get("legs") or [] if not demo(l.get("item_id"))]
    keep = [i for i in doc.get("replace_if_stale") or [] if not demo(i)]
    gone = {str(l.get("item_id")) for l in doc.get("legs") or []} - {str(l.get("item_id")) for l in legs}
    gone |= {str(i) for i in doc.get("replace_if_stale") or []} - {str(i) for i in keep}
    errs = [x for x in loaded.get("errors") or [] if not any(g in str(x) for g in gone) and "TRAIN-" not in str(x)]  # validation text echoes ids
    return {**loaded, "errors": errs, "doc": {**doc, "legs": legs, "replace_if_stale": keep}}


class LiveStore:
    """Read-only view of the store without demo/training items (F-49): digest, summary, holds, outcomes and the ledger list only real
    items. Everything else (single item lookups by id, chain verification, writes) passes through untouched."""

    def __init__(self, store):
        self._s = store

    def __getattr__(self, name):
        return getattr(self._s, name)

    @staticmethod
    def _demo(item) -> bool:
        """MBOS_UI_FIXTURE_ITEMS=1 (test suites whose only items are fixtures) turns the source-host rule off; TRAIN-* stays hidden.
        TRAIN-* fixtures, or an item whose sources are all reserved/fixture hosts (example.invalid). An item with no source at all is kept."""
        if live_demo.is_training(item):
            return True
        return not os.environ.get("MBOS_UI_FIXTURE_ITEMS") and (bool((item or {}).get("sources")) and not live_demo.has_verified_source(item))

    def _live(self, iid) -> bool:
        return not iid or not self._demo(self._s.item(iid))

    def items_in_states(self, *a, **k):
        return [i for i in self._s.items_in_states(*a, **k) if not self._demo(i)]

    def held(self, *a, **k):
        return [h for h in self._s.held(*a, **k) if self._live((h.get("item") or {}).get("item_id"))]

    def outcomes(self, *a, **k):
        return [o for o in self._s.outcomes(*a, **k) if self._live(o.get("item_id"))]

    def receipts(self, *a, **k):
        return [r for r in self._s.receipts(*a, **k) if self._live(r.get("item_id"))]


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
    return gazetteer.locate(base)


def origin_note(base: str, located: bool, radius) -> str:
    """Said out loud when the typed origin cannot be located, instead of silently ignoring the radius."""
    if located:
        return ""
    return (f"<div class='card'><b>Origin '{e(base)}' accepted but not located.</b> Distances are UNKNOWN"
            + (f" and the {radius:g} mi radius is not applied" if radius is not None else "")
            + ". Type a US ZIP or city in the local gazetteer (operator_ui/data/gazetteer_us.csv, or MBOS_GAZETTEER_FILE), or 'latitude, longitude'. No network lookup is made.</div>")


def photo_tile(url, listing_url) -> str:
    """A GSA image (ppms.gov) cannot load without a GSA login (HTTP 401), so show a clean tile, never a broken <img>. The URL stays in details."""
    link = f" <a href='{e(listing_url)}' rel='noopener noreferrer' target='_blank'>open</a>" if listing_url else ""
    det = f"<details class='small mut'><summary>image URL</summary><code>{e(url)}</code></details>" if url else ""
    return f"<div class='mk-nophoto small mut' style='width:120px'>{e(NO_PHOTO)}{link}{det}</div>"


def is_gsa_image(url) -> bool:
    return bool(re.match(r"^https?://([^/]*\.)?ppms\.gov(/|$)", str(url or ""), re.I))
