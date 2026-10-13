"""Customer settings keep each account's location/category defaults explicit."""

from operator_ui import account_view, market_browse, market_prefs, server


def test_settings_page_has_clean_customer_shell_and_honest_states(monkeypatch, tmp_path):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    server._CUR.path = "/settings"
    body = server.page("DealSniffer Settings", account_view.render("csrf", {"configured": False}), "RUNNING")
    assert "id='product-header'" in body and "Deal preferences" in body
    assert "Local owner mode" in body and "Google sign-in: <b>NOT CONFIGURED" in body
    assert body.count("<b>NOT CONNECTED</b>") >= 2 and "Email notifications: <b>NOT ACTIVE</b>" in body
    assert "DRY-RUN · nothing leaves this machine" not in body and "Operator UI" not in body


def test_saved_defaults_drive_a_fresh_market_visit(monkeypatch, tmp_path):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    assert account_view.save_preferences({"location": "72032", "radius": "30", "cat": "trailers,tools,equipment"}) == "Deal preferences saved."
    home = market_prefs.load()["ui"]["home"]
    assert home["zip"] == "72032" and home["radius"] == 30 and home["categories"] == ["trailers", "tools", "equipment"]
    assert market_browse.with_home({}) == {"loc_mode": ["distance"], "base": ["72032"], "radius": ["30"],
                                             "cat": ["trailers", "tools", "equipment"]}
