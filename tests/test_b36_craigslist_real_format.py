"""Craigslist alert e-mails in the layout OBSERVED on genuine alerts (Oct 14, 2026): sender alerts@alerts.craigslist.org, Gmail's
`dkim=pass header.i=@alerts.craigslist.org`, listing links https://www.craigslist.org/view/d/<town-title>/<opaque id>, the area only in the
"view all" link, and text that Craigslist encoded twice. Synthetic message (no real listing, account or token)."""

from __future__ import annotations

from datetime import datetime, timezone

from mbos_discovery.adapters.email_alerts import ORIGINS, EmailAlertAdapter, parse_alert, _slug_town

CL = ORIGINS["craigslist_email"]
HTML = (
    '<hr><p> <a href="https://www.craigslist.org/view/d/redfield-log-splitter/4EkwwNgQbzVFAnikJ9CUhx">Log splitter</a>  - $1,200\n'
    '<br><a href="https://www.craigslist.org/view/d/redfield-log-splitter/4EkwwNgQbzVFAnikJ9CUhx"><img src="https://images.craigslist.org/00E0E_fixture_300x300.jpg"></a></p>\n'
    '<hr><p> <a href="https://www.craigslist.org/view/d/conway-2006-ford-taurus-sel/uvgsVJWcSX7c3FjN1ozkxw">2006 Ford Taurus (Mechanicâ\u0080\u0099s Special)</a>'
    '  - $1,475 <small>(Conway)</small></p>\n'
    '<p><a href="https://www.craigslist.org/search/area/littlerock?cat=sss&query=log splitter">view all</a>\n'
    '<a href="https://accounts.craigslist.org/savesearch/edit?subID=1">edit</a></p>')


def _mail(auth: str = "dkim=pass header.i=@alerts.craigslist.org header.s=alerts-x header.b=AbCd;", sender="alerts@alerts.craigslist.org") -> bytes:
    return ("From: \"CL Search Alerts\" <" + sender + ">\r\nTo: a@example.invalid\r\nSubject: (2 new results) log splitter\r\n"
            "Date: Wed, 14 Oct 2026 22:38:39 +0000\r\nMessage-ID: <x@alerts.craigslist.org>\r\n"
            "Authentication-Results: mx.google.com;\r\n       " + auth + "\r\n       spf=pass\r\n"
            "MIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n" + HTML).encode("utf-8")


def test_view_links_region_from_view_all_and_gmail_dkim_identity():
    facts, ls = parse_alert(CL, _mail())
    assert [l.listing_id for l in ls] == ["4EkwwNgQbzVFAnikJ9CUhx", "uvgsVJWcSX7c3FjN1ozkxw"]
    assert ls[0].url == "https://www.craigslist.org/view/d/redfield-log-splitter/4EkwwNgQbzVFAnikJ9CUhx"
    assert {l.region for l in ls} == {"littlerock"} and ls[0].thumb == "https://images.craigslist.org/00E0E_fixture_300x300.jpg"
    assert ls[1].title == "2006 Ford Taurus (Mechanic’s Special)"          # double-encoded text repaired


def test_unauthenticated_or_foreign_dkim_is_still_quarantined():
    import pytest
    from mbos_discovery.adapter import NormalizationError
    for auth in ("dkim=fail header.i=@alerts.craigslist.org;", "dkim=pass header.i=@evil.example;", "dkim=pass header.i=@craigslist.org.evil.example;"):
        with pytest.raises(NormalizationError):
            parse_alert(CL, _mail(auth))


def test_normalized_item_carries_state_price_and_both_town_texts():
    ad = EmailAlertAdapter("craigslist_email", None, clock=lambda: datetime(2026, 10, 14, 23, tzinfo=timezone.utc))
    src = _mail().decode("utf-8")
    n0 = ad.normalize({"origin": "craigslist_email", "email_source": src, "listing_index": 0}, datetime(2026, 10, 14, 23, tzinfo=timezone.utc))
    n1 = ad.normalize({"origin": "craigslist_email", "email_source": src, "listing_index": 1}, datetime(2026, 10, 14, 23, tzinfo=timezone.utc))
    assert n0.normalized["price"]["amount"] == 1200.0 and n0.normalized["location"] == {"state": "AR"}
    assert "(as shown, unverified): UNKNOWN" in n0.normalized["description"] and "Town in listing link (unverified): redfield" in n0.normalized["description"]
    assert "(as shown, unverified): Conway" in n1.normalized["description"] and n1.normalized["price"]["amount"] == 1475.0


def test_slug_town():
    assert _slug_town("https://www.craigslist.org/view/d/damascus-24-14k-heavy-duty-equipment/x1234567890", "24' 14K Heavy Duty Equipment Trailer") == "damascus"
    assert _slug_town("https://www.craigslist.org/view/d/little-rock-mini-excavators-skid-steer/x1234567890", "Mini Excavators, Skid Steer") == "little rock"
    assert _slug_town("https://www.craigslist.org/view/d/log-splitter/x1234567890", "Log splitter") == ""
