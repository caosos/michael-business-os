"""eBay Marketplace Insights adapter — sold comps (C-04 source side), ADR-02-0202 tier 1 (official API).

FACT (developer.ebay.com Marketplace Insights overview / release notes, read 2026-10-07): `item_sales` search returns
the sales history of items sold up to 90 days back, and has a `lastSoldDate` filter. It is a **Limited Release** API, open
only to developers eBay approves, with per-partner category allow-lists.
UNKNOWN until approved access: the exact response shape. Fixtures follow eBay's published naming
(`itemSales[]`, `lastSoldPrice{value,currency}`, `lastSoldDate`, `totalSoldQuantity`, `condition`, `itemLocation`,
`itemWebUrl`) and must be re-recorded on first live call.

Live use needs BOTH `live=True` and credentials whose keyset has the insights scope; otherwise a safe `config`
error with zero requests. Reuses the Browse adapter's read-only OAuth client-credentials path.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from ..adapter import FetchResult, NormalizationError, SearchProfile, SourceError
from ..comps import CompDraft, CompSourceAdapter, FLIP_CATEGORIES, _condition, _sold_date
from ..normalize import classify, clean_text, match_text, money
from .ebay_browse import EbayBrowseAdapter, _condition as _ebay_condition, _utcnow

INSIGHTS_SCOPE = "https://api.ebay.com/oauth/api_scope/buy.marketplace.insights"


class EbayInsightsAdapter(EbayBrowseAdapter, CompSourceAdapter):
    source = "ebay_marketplace_insights"   # name agreed with Agent 03 comps_sources registry
    ingestion_method = "api"
    tos_risk = "low"
    access_tier = 1
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, client_id, client_secret, env: str = "production", *, live: bool = False, **kw) -> None:
        super().__init__(client_id, client_secret, env, **kw)
        self.live = live
        self.scope = INSIGHTS_SCOPE
        self.list_key = "itemSales"

    @classmethod
    def from_env(cls, environ, *, live: bool = False, **kw) -> "EbayInsightsAdapter":
        return cls(environ.get("EBAY_CLIENT_ID"), environ.get("EBAY_CLIENT_SECRET"),
                   environ.get("EBAY_ENV", "production"), live=live, **kw)

    @classmethod
    def from_fixture(cls, fixture_dir: str | Path, clock: Callable[[], datetime] = _utcnow) -> "EbayInsightsAdapter":
        """Recorded-style responses served by the Browse fixture handler (token.json, search-<slug(q)>.json)."""
        transport = EbayBrowseAdapter.from_fixture(fixture_dir, clock).http._inner
        return cls("fixture-client", "fixture-secret", live=True, transport=transport, clock=clock)

    def fetch(self, profile: SearchProfile) -> FetchResult:
        if not self.live:
            return FetchResult(self.source, error=SourceError(
                "config", "live eBay Marketplace Insights calls not enabled (set live = true; Limited Release access required)"))
        res = super().fetch(profile)
        res.source = self.source
        return res

    def _search_url(self, q: str, p: SearchProfile) -> str:
        params = {"q": q, "limit": str(min(max(p.limit, 1), 200)), "offset": "0",
                  "filter": "conditions:{USED|UNSPECIFIED},priceCurrency:USD"}
        return f"{self.base}/buy/marketplace_insights/v1_beta/item_sales/search?{urlencode(params)}"

    def normalize(self, s: dict, fetched_at: datetime) -> CompDraft:
        if not isinstance(s, dict) or not s.get("itemId") or not s.get("title"):
            raise NormalizationError("item sale missing itemId/title")
        sold = s.get("lastSoldPrice") or {}
        price = money(sold.get("value"))
        if not price:
            raise NormalizationError("item sale has no positive lastSoldPrice")
        currency = clean_text(sold.get("currency") or "USD").upper()
        title = clean_text(s["title"], 300)
        cats = " ".join(c.get("categoryName", "") for c in s.get("categories") or [] if isinstance(c, dict))
        category, _ = classify("flip", match_text(title), match_text(title, cats))
        if category not in FLIP_CATEGORIES:
            category = "other_asset"
        loc_in = s.get("itemLocation") or {}
        loc = {k: v for k, v in {"city": clean_text(loc_in.get("city")) or None,
                                 "state": clean_text(loc_in.get("stateOrProvince")) or None,
                                 "zip": clean_text(loc_in.get("postalCode")) or None}.items() if v}
        cond = _ebay_condition(s) if (s.get("conditionId") or s.get("condition")) else "unknown"
        return CompDraft(source_comp_id=str(s["itemId"]), price=price, currency=currency,
                         sold_date=_sold_date(s.get("lastSoldDate"), fetched_at),
                         url=clean_text(s.get("itemWebUrl")) or f"ebay-item://{s['itemId']}",
                         category=category, title=title, condition=_condition(cond), location=loc)
