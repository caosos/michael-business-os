"""eBay Browse request shape, OAuth handling and field mapping (live path, offline)."""

import base64
import json
from urllib.parse import parse_qs, urlsplit

from conftest import FIX, FLIP, T0, Clock
from mbos_discovery.adapters import EbayBrowseAdapter
from mbos_discovery.http import CallbackTransport, HttpResponse

TOKEN = (FIX / "ebay" / "token.json").read_bytes()


def _adapter(handler, **kw):
    return EbayBrowseAdapter("cid", "csecret", transport=CallbackTransport(handler), clock=Clock(), **kw)


def test_token_request_and_search_request_shape():
    seen = []

    def handler(m, u, h, b):
        seen.append((m, u, h, b))
        return HttpResponse(200, TOKEN) if m == "POST" else HttpResponse(200, b'{"itemSummaries":[]}')

    _adapter(handler).fetch(FLIP)
    m, u, h, b = seen[0]
    assert m == "POST" and u == "https://api.ebay.com/identity/v1/oauth2/token"
    assert h["Authorization"] == "Basic " + base64.b64encode(b"cid:csecret").decode()
    assert parse_qs(b.decode()) == {"grant_type": ["client_credentials"],
                                    "scope": ["https://api.ebay.com/oauth/api_scope"]}
    m, u, h, _ = seen[1]
    q = parse_qs(urlsplit(u).query)
    assert q["q"] == ["utility trailer"] and h["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"
    assert h["Authorization"] == "Bearer v^1.1#FIXTURE-TOKEN"
    f = q["filter"][0]
    for part in ("conditions:{USED}", "pickupPostalCode:72034", "pickupRadius:100", "pickupRadiusUnit:mi",
                 "deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}", "price:[..5000]"):
        assert part in f
    assert sum(1 for s in seen if s[0] == "POST") == 1      # token cached across queries


def test_401_refreshes_token_once():
    n = {"get": 0, "post": 0}

    def handler(m, u, h, b):
        if m == "POST":
            n["post"] += 1
            return HttpResponse(200, TOKEN)
        n["get"] += 1
        return HttpResponse(401 if n["get"] == 1 else 200, b'{"itemSummaries":[]}')

    res = _adapter(handler).fetch(FLIP)
    assert res.ok and n["post"] == 2


def test_bad_credentials_is_auth_error():
    res = _adapter(lambda m, u, h, b: HttpResponse(401, b'{"error":"invalid_client"}')).fetch(FLIP)
    assert res.error.kind == "auth" and not res.records


def test_sandbox_environment_hosts():
    ad = EbayBrowseAdapter("a", "b", env="sandbox")
    assert ad.token_url.startswith("https://api.sandbox.ebay.com/")


def test_field_mapping_fixed_price():
    ad = EbayBrowseAdapter.from_fixture(FIX / "ebay")
    s = json.loads((FIX / "ebay" / "search-utility-trailer.json").read_text())["itemSummaries"][0]
    n = ad.normalize(s, T0)
    assert (n.type, n.category, n.opportunity_kind) == ("flip", "trailer", "buy_item")
    assert n.normalized["price"] == {"amount": 1200.0, "currency": "USD", "type": "fixed"}
    assert n.normalized["location"] == {"city": "Conway", "state": "AR", "zip": "720**", "geo_tier": 0}
    assert n.normalized["counterparty"] == {"role": "seller", "contact_method": "platform",
                                            "name": "conway_trailers", "is_dealer": False}
    assert n.url == "https://www.ebay.com/itm/110000000001"


def test_field_mapping_auction_and_flags():
    ad = EbayBrowseAdapter.from_fixture(FIX / "ebay")
    s = json.loads((FIX / "ebay" / "search-utility-trailer.json").read_text())["itemSummaries"][1]
    n = ad.normalize(s, T0)
    assert n.opportunity_kind == "auction_lot"
    assert n.normalized["price"]["type"] == "starting_bid" and n.normalized["bid_count"] == 0
    assert n.normalized["ends_at"] == "2026-10-07T20:00:00Z"
    assert set(n.normalized["flags"]) == {"zero_bid", "ending_soon", "long_distance"}


def test_parts_condition_and_unclassified():
    ad = EbayBrowseAdapter.from_fixture(FIX / "ebay")
    items = json.loads((FIX / "ebay" / "search-generator.json").read_text())["itemSummaries"]
    assert ad.normalize(items[0], T0).normalized["condition"] == "parts"
    lamp = ad.normalize(items[3], T0)
    assert lamp.category == "other_asset" and "needs_review" in lamp.normalized["flags"]
