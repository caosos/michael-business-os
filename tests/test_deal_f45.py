"""F-45: DEMO vs live link, HTML injection, missing photo, filters/presets/tow, active nav, milestones. TEST data only; DRY-RUN."""
import copy

from operator_ui import deal_ui, resale_view as rv
from tests.conftest import PIN
from tests.test_operator_ui import req

LIVE = "https://www.govdeals.com/en/asset/123/456"


def test_link_rules():
    assert deal_ui.classify_url(LIVE)[0] == "live" and deal_ui.classify_url("http://sub.govdeals.com/x")[0] == "live"
    assert deal_ui.classify_url("https://listings.example.invalid/lot/1")[0] == "demo"
    assert deal_ui.classify_url(None)[0] == deal_ui.classify_url("  ")[0] == "none"
    for bad in ("javascript:alert(1)", "data:text/html,<b>", "ftp://www.govdeals.com/x", "//www.govdeals.com/x", "https://evil.example.org.attacker.net/x",
                "https://www.govdeals.com.evil.net/x", "https://user:pw@www.govdeals.com/x", "https://www.govdeals.com/x y",
                "https://www.govdeals.com/out?url=https://evil.net", "https://www.govdeals.com/out?next=//evil.net", "https://www.govdeals.com\\@evil.net"):
        assert deal_ui.classify_url(bad)[0] == "rejected", bad
    live = deal_ui.render_link({"url": LIVE})
    assert "View original listing" in live and "rel='noopener noreferrer nofollow'" in live and f'href="{LIVE}"' in live
    assert "<a " not in deal_ui.render_link({"url": 'https://www.govdeals.com/a"onmouseover="x'})
    for u in (None, "javascript:alert(1)", "https://not-allowed.net/x"):
        h = deal_ui.render_link({"url": u})
        assert "No verified live link" in h and "<a " not in h


def test_demo_fixture_is_labelled_and_never_a_link(ui):
    b = req(ui, "GET", "/resale")[2]
    assert "example.invalid" in b and "not a live listing and is not clickable" in b and "<span class=lbl>DEMO</span>" in b
    assert "href=\"https://listings.example.invalid" not in b and "href='https://listings.example.invalid" not in b
    ui.deals["live-1"] = {**copy.deepcopy(rv.DEMO_DEALS["demo-utility-trailer"]), "item_id": "live-1", "title": "TEST live trailer", "demo": False, "url": LIVE}
    b = req(ui, "GET", "/resale")[2]
    assert f'href="{LIVE}"' in b and "View original listing" in b


def test_hostile_text_is_escaped_and_ad_is_verbatim(ui):
    evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    ad = "Line one\nLine <b>two</b>\n" + "\n".join(f"more {i}" for i in range(12)) + "\n" + evil
    ui.deals["evil"] = {**copy.deepcopy(rv.DEMO_DEALS["demo-utility-trailer"]), "item_id": "evil", "title": evil, "demo": False, "location": evil,
                        "description": ad, "condition": evil, "url": 'https://www.govdeals.com/"><script>alert(3)</script>',
                        "photos": [{"url": 'https://cdn.net/a.jpg"><script>alert(4)</script>', "source": evil}]}
    b = req(ui, "GET", "/resale")[2]
    assert "<script>alert" not in b and "onerror=alert" not in b.replace("&lt;img src=x onerror=alert(2)&gt;", "")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in b and "Line &lt;b&gt;two&lt;/b&gt;\nmore 0" in b       # verbatim, line breaks kept, escaped
    assert "Show full ad" in b
    h = deal_ui.render_description({"description": "short\nad"})
    assert "Show full ad" not in h and "short\nad" in h
    assert "none captured" in deal_ui.render_description({})


def test_photos_cover_count_provenance_fallback_and_mockups_apart():
    d = {"source": "Seller site", "photos": [{"url": "https://cdn.photos.net/a.jpg", "source": "GovDeals", "captured_at": "2026-10-09"},
                                              {"url": "https://cdn.photos.net/b.jpg", "expired": True},
                                              {"url": "https://cdn.photos.net/m.jpg", "kind": "mockup", "source": "Mockup tool"}]}
    h = deal_ui.render_gallery(d)
    assert "<b>2</b> original photos" in h and "GovDeals" in h and "captured 2026-10-09" in h and "Enlarge / all photos" in h
    assert "Photo expired or removed by the source" in h and h.count("<img ") == 3          # cover + enlarged original + mockup (the expired one is not loaded)
    orig, _, mock = h.partition("Mockup (not the real item)")
    assert "m.jpg" not in orig and "m.jpg" in mock and "never the seller's photo" in mock
    none = deal_ui.render_gallery({"photos": []})
    assert "No original photo" in none and "0 photos" in none and "<img" not in none
    assert "<img" not in deal_ui.render_gallery({"photos": [{"url": "javascript:alert(1)"}, {"url": "data:image/png;base64,AA"}, {"url": "https://img.example.invalid/x.jpg"}]})
    only_mock = deal_ui.render_gallery({"photos": [{"url": "https://cdn.photos.net/m.jpg", "kind": "mockup"}]})
    assert "0 photos" in only_mock and "No original photo" in only_mock


def test_glance_card_has_the_fields_and_proof_is_collapsed(ui):
    b = req(ui, "GET", "/resale")[2]
    for s in ("Price now", "Distance", "Condition", "SOLD comps", "ASKING comps", "Expected net", "Profit / hour", "Days to cash", "Max bid", "<b>Next:</b>", "View proof"):
        assert s in b
    i = b.index("View proof")
    assert b.index("Raw JSON") > i and "<details class='proof'>" in b


def test_filters_explain_and_never_delete(ui):
    n = len(ui.deals)
    b = req(ui, "GET", "/resale?max_distance=30&find=1")[2]
    assert "Find Deals Now ran (DRY-RUN)" in b and "No live source is connected" in b
    assert "1 deal(s) hidden by your filters" in b and "25 mi" not in b.split("hidden by your filters")[1][:200] and "32 mi is farther than 30 mi" in b
    assert len(ui.deals) == n
    b = req(ui, "GET", "/resale?sale_type=fixed")[2]
    assert "it is a auction sale, not fixed" in b
    b = req(ui, "GET", "/resale?max_distance=abc&profit_at_least=")[2]
    assert "ignored &#x27;abc&#x27; for max_distance" in b and "hidden by your filters" not in b
    b = req(ui, "GET", "/resale?closing_soon=1&confidence=HIGH&title_status=clean&max_days=5&max_price=100&min_price=1&condition=x&category=y&subtype=z")[2]
    assert b.count("deal(s) hidden") == 1


def test_tow_limits_are_editable_and_drive_transport_filter(ui):
    assert "limit UNKNOWN lb" in req(ui, "GET", "/resale")[2] and "tow check UNKNOWN" in req(ui, "GET", "/resale")[2]
    bad = req(ui, "POST", "/resale/tow", {"csrf": ui.csrf, "pin": "bad", "tow_limit_lb": "2000"})
    assert not ui.tow and bad[0] == 200
    assert req(ui, "POST", "/resale/tow", {"csrf": ui.csrf, "pin": PIN, "vehicle": "TEST pickup", "tow_limit_lb": "2000"})[0] == 303
    assert ui.tow["tow_limit_lb"] == 2000.0
    b = req(ui, "GET", "/resale?transport=can_tow")[2]
    assert "2,800 lb is over your 2,000 lb tow limit" in b and "demo-splitter" in b
    assert "can tow" in req(ui, "GET", "/resale")[2]
    req(ui, "POST", "/resale/tow", {"csrf": ui.csrf, "pin": PIN, "vehicle": "TEST truck", "tow_limit_lb": "9000"})   # edited, not fixed
    assert ui.tow["tow_limit_lb"] == 9000.0 and "hidden by your filters" not in req(ui, "GET", "/resale?transport=can_tow")[2]
    assert req(ui, "POST", "/resale/tow", {"csrf": ui.csrf, "pin": PIN, "tow_limit_lb": "-5"})[0] == 200
    assert req(ui, "POST", "/resale/tow", {"csrf": "x", "pin": PIN, "tow_limit_lb": "5"})[0] == 200 and ui.tow["tow_limit_lb"] == 9000.0


def test_presets_save_and_apply(ui):
    assert req(ui, "POST", "/resale/preset", {"csrf": "bad", "name": "n", "max_distance": "30"})[0] == 200 and not ui.presets
    s, loc, _ = req(ui, "POST", "/resale/preset", {"csrf": ui.csrf, "name": "Near <b>me</b>", "max_distance": "30", "bogus": "1"})
    assert s == 303 and ui.presets == {"Near <b>me</b>": {"max_distance": 30.0}}
    b = req(ui, "GET", "/resale?preset=Near%20%3Cb%3Eme%3C%2Fb%3E")[2]
    assert "hidden by your filters" in b and "Near &lt;b&gt;me&lt;/b&gt;" in b and "Near <b>me</b>" not in b


def test_chrome_active_nav_heading_and_milestones(ui):
    b = req(ui, "GET", "/resale")[2]
    assert '<a href="/resale" class=active aria-current=page>Resale</a>' in b and b.count("aria-current=page") == 1
    assert '<h1 class="pagehead">Resale</h1>' in b
    for s in ("Usable now", "Blocked", "Future", "Daily search", "Live auction connector", "Overnight negotiation", "No dates are promised"):
        assert s in b
    t = req(ui, "GET", "/numbers")[2]
    assert 'href="/numbers" class=active' in t and 'href="/resale" class=active' not in t


def test_reference_notes_name_the_true_blocker(ui):
    b = req(ui, "GET", "/notes")[2]
    assert "Notes need the lane D store" in b
    s, _, out = req(ui, "POST", "/notes/add", {"csrf": ui.csrf, "pin": PIN, "category": "trailer", "makes": "A", "models": "B", "kind": "known_weakness", "statement": "x" * 40})
    assert s == 200 and ("lane D store" in out or "Not saved" in out)


def test_dump_pages_for_screenshots(ui, tmp_path):
    """Writes the rendered pages when MBOS_SHOT_DIR is set (used for the 1648/1280/390 px screenshots); otherwise a no-op."""
    import os
    out = os.environ.get("MBOS_SHOT_DIR")
    if not out:
        return
    ui.deals["live-shot"] = {**copy.deepcopy(rv.DEMO_DEALS["demo-utility-trailer"]), "item_id": "live-shot", "title": "TEST live 14 ft trailer", "demo": False, "url": LIVE,
                             "photos": [{"url": "https://cdn.photos.net/a.jpg", "source": "GovDeals", "captured_at": "2026-10-09"}, {"url": "https://cdn.photos.net/b.jpg", "expired": True}]}
    req(ui, "POST", "/resale/tow", {"csrf": ui.csrf, "pin": PIN, "vehicle": "TEST pickup", "tow_limit_lb": "2000"})
    for name, path in (("resale", "/resale"), ("resale-filtered", "/resale?transport=can_tow&find=1"), ("notes", "/notes")):
        (os.path.join(out, name + ".html") and open(os.path.join(out, name + ".html"), "w")).write(req(ui, "GET", path)[2])
