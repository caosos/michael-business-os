"""Account/OAuth foundation tests intentionally require only the standard library."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from operator_ui import accounts, market_prefs


def configured(**overrides):
    env = {
        "MBOS_GOOGLE_CLIENT_ID": "client.apps.googleusercontent.com",
        "MBOS_GOOGLE_CLIENT_SECRET": "provider-secret",
        "MBOS_GOOGLE_REDIRECT_URI": "https://deals.example/auth/google/callback",
        "MBOS_SESSION_SECRET": "s" * 32,
    }
    env.update(overrides)
    return env


def test_google_config_is_disabled_by_default_and_never_exposes_secrets():
    assert accounts.google_oauth_config({}).public_status() == {
        "provider": "google", "configured": False, "redirect_uri": None,
        "scopes": ["openid", "email", "profile"],
    }
    cfg = accounts.google_oauth_config(configured())
    assert cfg.enabled and cfg.scopes == ("openid", "email", "profile")
    assert "secret" not in json.dumps(cfg.public_status()).lower()
    assert "provider-secret" not in repr(cfg) and "s" * 32 not in repr(cfg)


@pytest.mark.parametrize("change", [
    {"MBOS_GOOGLE_CLIENT_SECRET": ""},
    {"MBOS_SESSION_SECRET": "short"},
    {"MBOS_GOOGLE_REDIRECT_URI": "http://deals.example/auth/google/callback"},
    {"MBOS_GOOGLE_REDIRECT_URI": "https://user:pass@deals.example/cb"},
    {"MBOS_GOOGLE_REDIRECT_URI": "https://deals.example/cb#fragment"},
    {"MBOS_GOOGLE_REDIRECT_URI": "https://deals.example/auth/google/callback?extra=1"},
    {"MBOS_GOOGLE_REDIRECT_URI": "https://deals.example/callback"},
])
def test_google_config_fails_closed_when_partial_or_unsafe(change):
    with pytest.raises(accounts.AccountConfigError):
        accounts.google_oauth_config(configured(**change))
    assert accounts.google_oauth_config(configured(
        MBOS_GOOGLE_REDIRECT_URI="http://127.0.0.1:8766/auth/google/callback")).enabled


def test_session_is_signed_expires_and_contains_no_profile_data():
    acct = accounts.google_account("108812345678901234567", "michael@example.com", "Michael")
    signer = accounts.SessionSigner("x" * 32, ttl_seconds=600)
    token = signer.issue(acct, now=1_000)
    assert signer.verify(token, now=1_599) == acct.user_id
    assert "michael" not in token.lower() and "example.com" not in token
    with pytest.raises(accounts.InvalidSession):
        signer.verify(token[:-1] + ("A" if token[-1] != "A" else "B"), now=1_001)
    with pytest.raises(accounts.InvalidSession):
        signer.verify(token, now=1_600)
    cookie = signer.cookie(token)
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie


def test_profiles_and_preferences_are_isolated_without_provider_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "local.json"))
    first = accounts.google_account("google-sub-1", "one@example.com", "One")
    second = accounts.google_account("google-sub-2", "two@example.com", "Two")
    store = accounts.AccountStore()
    profile_path = store.save_google_profile(first)
    assert profile_path.stat().st_mode & 0o077 == 0
    assert store.load_google_profile(first.user_id) == first
    assert "token" not in profile_path.read_text().lower()

    with accounts.use(first):
        market_prefs.remember({"base": ["72032"], "radius": ["30"]})
        first_path = market_prefs.path()
    with accounts.use(second):
        assert market_prefs.recall(("base", "radius")) == {}
        assert market_prefs.load()["ui"]["home"] == {"state": "", "zip": "", "label": ""}
        market_prefs.remember({"base": ["Little Rock AR"]})
        second_path = market_prefs.path()
    assert first_path != second_path
    with accounts.use(first):
        assert market_prefs.recall(("base", "radius")) == {"base": ["72032"], "radius": ["30"]}
    assert market_prefs.path() == Path(tmp_path / "local.json")
