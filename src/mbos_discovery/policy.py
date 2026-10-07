"""Source access policy (ADR-02-0202, ACCEPTED; MICHAEL_DECISIONS #3).

Three dispositions:

* ALLOWED          — official API or a channel we own (inbound form). Runs when configured.
* PENDING_MICHAEL  — ToS-adverse internal endpoints / browser automation. Never runs unless
                     the source is explicitly enabled per-source by Michael's decision (P2).
* FORBIDDEN        — the do-not-automate list. Refused unconditionally; no flag overrides it.

Unknown sources are treated as PENDING_MICHAEL (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Disposition(str, Enum):
    ALLOWED = "allowed"
    PENDING_MICHAEL = "pending_michael"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class SourcePolicy:
    source: str
    disposition: Disposition
    tier: int
    tos_risk: str
    note: str


_P = SourcePolicy
REGISTRY: dict[str, SourcePolicy] = {p.source: p for p in [
    # Tier 1 — official APIs / owned channels
    _P("ebay", Disposition.ALLOWED, 1, "low", "eBay Browse API, OAuth client-credentials, read-only"),
    _P("gsa_auctions", Disposition.ALLOWED, 1, "low", "GSA Auctions API (api.gsa.gov) — next adapter"),
    _P("samgov", Disposition.ALLOWED, 1, "low", "SAM.gov Opportunities API v2 — next adapter"),
    _P("trashnothing", Disposition.ALLOWED, 1, "low", "Trash Nothing REST API — next adapter"),
    _P("website_lead", Disposition.ALLOWED, 1, "low", "our own website form submissions"),
    _P("referral", Disposition.ALLOWED, 1, "low", "referral intake recorded by Michael"),
    _P("nhtsa", Disposition.ALLOWED, 1, "low", "NHTSA recalls/complaints by vehicle (official API, read-only); knowledge, not Items"),
    _P("cpsc_recalls", Disposition.ALLOWED, 1, "low", "CPSC Recalls Retrieval Web Services (official API, read-only); knowledge, not Items"),
    _P("ebay_marketplace_insights", Disposition.ALLOWED, 1, "low",
       "eBay Marketplace Insights (sold comps) — Limited Release; needs eBay approval + live flag"),
    # Tier 2 — sanctioned email alerts in our own inbox
    _P("govdeals_email", Disposition.ALLOWED, 2, "low", "GovDeals saved-search alert emails in our own inbox"),
    _P("publicsurplus_email", Disposition.ALLOWED, 2, "low", "PublicSurplus alert emails in our own inbox"),
    _P("estatesales_net_email", Disposition.ALLOWED, 2, "low",
       "EstateSales.NET alert emails (site scraping stays FORBIDDEN; email is the sanctioned path)"),
    # Tier 5 — human-entered evidence (Michael / Operator UI), with human provenance
    _P("manual", Disposition.ALLOWED, 5, "low", "sold comps recorded by a human, with provenance"),
    # Tier 3/4 — gray zone, needs explicit per-source enablement (P2)
    _P("craigslist", Disposition.PENDING_MICHAEL, 3, "med", "Cloudflare-gated; experimental only after live test"),
    _P("govdeals", Disposition.PENDING_MICHAEL, 3, "med", "buyer access only via internal JSON"),
    _P("hibid", Disposition.PENDING_MICHAEL, 3, "med", "public GraphQL LotSearch, ToS-adverse"),
    _P("allsurplus", Disposition.PENDING_MICHAEL, 3, "med", "internal search endpoint"),
    _P("publicsurplus", Disposition.PENDING_MICHAEL, 3, "med", "internal endpoint"),
    _P("municibid", Disposition.PENDING_MICHAEL, 3, "med", "internal endpoint"),
    _P("offerup", Disposition.PENDING_MICHAEL, 4, "high", "browser automation"),
    # Do-not-automate (research §5) — refused unconditionally
    _P("facebook_marketplace", Disposition.FORBIDDEN, 5, "high", "no FB automation in wave one"),
    _P("facebook_groups", Disposition.FORBIDDEN, 5, "high", "ToS bans extraction; manual only"),
    _P("nextdoor", Disposition.FORBIDDEN, 5, "high", "login-walled personal content; manual only"),
    _P("thumbtack_site", Disposition.FORBIDDEN, 5, "high", "PII harvesting; use official lead API only"),
    _P("angi_site", Disposition.FORBIDDEN, 5, "high", "PII harvesting; use official lead API only"),
    _P("homeadvisor_site", Disposition.FORBIDDEN, 5, "high", "PII harvesting; use official lead API only"),
    _P("estatesales_net_site", Disposition.FORBIDDEN, 5, "high", "ToS §16 bans robots; use email alerts"),
    _P("estatesales_org", Disposition.FORBIDDEN, 5, "high", "hostile terms; avoid entirely"),
]}


class SourceRefused(Exception):
    pass


def policy_for(source: str) -> SourcePolicy:
    return REGISTRY.get(source) or SourcePolicy(source, Disposition.PENDING_MICHAEL, 5, "high",
                                                "unregistered source — fail closed")


def check_allowed(source: str, explicitly_enabled: frozenset[str] = frozenset()) -> SourcePolicy:
    """Raise SourceRefused unless this source may be collected right now."""
    pol = policy_for(source)
    if pol.disposition is Disposition.FORBIDDEN:
        raise SourceRefused(f"{source}: on the do-not-automate list ({pol.note})")
    if pol.disposition is Disposition.PENDING_MICHAEL and source not in explicitly_enabled:
        raise SourceRefused(f"{source}: requires explicit per-source enablement (MICHAEL_DECISIONS #3)")
    return pol
