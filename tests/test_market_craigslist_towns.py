"""Craigslist alert place text (seller-typed, unverified) -> gazetteer town; anything that does not resolve stays UNKNOWN (never local)."""
from operator_ui import market_sources as m


def test_town_spellings_resolve():
    for text, want in (("Warren Arkansas", "Warren"), ("N little rock ar", "North Little Rock"), ("Jax", "Jacksonville"),
                       ("West little Rock", "Little Rock"), ("cabot", "Cabot"), ("Conway", "Conway"), ("bigelow ar", "Bigelow")):
        hit = m._town(text, "AR")
        assert hit and hit[0] == want, text


def test_unknown_and_junk_stay_unknown():
    for text in ("UNKNOWN", "", "CALL 501-557-6154 FOR AVAILABILITY", "Northwest"):
        assert m._town(text, "AR") is None, text
