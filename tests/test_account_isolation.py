"""Cross-account storage boundaries for customer-owned DealSniffer data."""

from __future__ import annotations

from pathlib import Path

from operator_ui import accounts, market_bids, market_prefs, sell_intake


def _sell(title: str, claimed_user: str) -> dict:
    # claimed_user is deliberate hostile extra form data.  parse() ignores it,
    # and Store.append() derives the account marker from request context.
    return sell_intake.parse({
        "user_id": claimed_user,
        "relationship": "owner",
        "name": "Test owner",
        "email": "owner@example.com",
        "contact_permission": "yes",
        "authority_attestation": "yes",
        "title": title,
        "category": "Trailer",
        "location": "Conway, AR",
        "condition": "needs repair",
        "desired_outcome": "Consignment",
    }, "2026-10-13T06:00:00Z", "sell-" + title.lower().replace(" ", "-"))


def _bid(title: str, now: str) -> None:
    market_bids.act("add", {
        "title": title,
        "source": "Public Surplus",
        "url": "https://example.test/" + title.lower().replace(" ", "-"),
        "current_bid": "125",
        "max_bid": "300",
        "status": "watching",
    }, now)


def test_customer_preferences_saved_hidden_bids_and_sell_intake_are_isolated(tmp_path, monkeypatch):
    account_root = tmp_path / "accounts"
    local_prefs = tmp_path / "owner-market.json"
    local_sell = tmp_path / "owner-sell.jsonl"
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(account_root))
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(local_prefs))
    monkeypatch.setenv("MBOS_SELL_INTAKE_FILE", str(local_sell))

    one = accounts.google_account("google-one", "one@example.com", "One")
    two = accounts.google_account("google-two", "two@example.com", "Two")
    profiles = accounts.AccountStore()
    profiles.save_google_profile(one)
    profiles.save_google_profile(two)
    inbox = sell_intake.Store()

    with accounts.use(one):
        market_prefs.act("save", "one-saved", "One's saved trailer")
        market_prefs.act("hide", "one-hidden", "One's hidden mower")
        _bid("One Bid", "2026-10-13T06:01:00+00:00")
        inbox.append(_sell("One Tractor", two.user_id))
        one_prefs, one_sell = market_prefs.path(), inbox.path

    with accounts.use(two):
        before = market_prefs.load()
        assert before["saved"] == [] and before["hidden"] == {} and before["bids"] == {}
        assert inbox.recent() == []
        market_prefs.act("save", "two-saved", "Two's saved tool")
        market_prefs.act("hide", "two-hidden", "Two's hidden trailer")
        _bid("Two Bid", "2026-10-13T06:02:00+00:00")
        inbox.append(_sell("Two Mower", one.user_id))
        two_prefs, two_sell = market_prefs.path(), inbox.path
        assert [r["item"]["title"] for r in inbox.recent()] == ["Two Mower"]
        assert inbox.recent()[0]["account_key"] == two.storage_key

    assert len({one_prefs, two_prefs, one_sell, two_sell}) == 4
    assert one.storage_key in one_prefs.parts and one.storage_key in one_sell.parts
    assert two.storage_key in two_prefs.parts and two.storage_key in two_sell.parts

    with accounts.use(one):
        doc = market_prefs.load()
        assert doc["saved"] == ["one-saved"]
        assert set(doc["hidden"]) == {"one-hidden"}
        assert [r["title"] for r in doc["bids"].values()] == ["One Bid"]
        assert [r["item"]["title"] for r in inbox.recent()] == ["One Tractor"]
        assert inbox.recent()[0]["account_key"] == one.storage_key

    for path in (one_prefs, two_prefs, one_sell, two_sell):
        assert path.stat().st_mode & 0o077 == 0
        assert path.parent.stat().st_mode & 0o077 == 0

    # Profiles are keyed from the verified provider subject, not from a form,
    # and loading one subject never returns the other profile.
    assert profiles.load_google_profile(one.user_id) == one
    assert profiles.load_google_profile(two.user_id) == two


def test_local_owner_paths_and_existing_data_are_not_moved(tmp_path, monkeypatch):
    prefs = tmp_path / "michael-market.json"
    sell = tmp_path / "michael-sell.jsonl"
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(prefs))
    monkeypatch.setenv("MBOS_SELL_INTAKE_FILE", str(sell))

    inbox = sell_intake.Store()
    market_prefs.act("save", "owner-saved", "Michael's saved listing")
    inbox.append(_sell("Owner Trailer", "google-someone-else"))

    assert market_prefs.path() == prefs
    assert inbox.path == sell
    assert market_prefs.load()["saved"] == ["owner-saved"]
    assert [r["item"]["title"] for r in inbox.recent()] == ["Owner Trailer"]
    assert not (tmp_path / "accounts" / accounts.LOCAL_OWNER.storage_key).exists()


def test_account_filename_rejects_path_components(tmp_path):
    user = accounts.google_account("google-path-check")
    with accounts.use(user):
        try:
            accounts.account_file_path(tmp_path / "owner.json", "../escape.json")
        except ValueError as ex:
            assert "plain filename" in str(ex)
        else:  # pragma: no cover - explicit failure gives a clearer message
            raise AssertionError("path traversal filename was accepted")
