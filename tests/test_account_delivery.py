from __future__ import annotations

import json

import pytest

from operator_ui import account_delivery as ad


CFG = ad.AliasConfig("dealsniffers.com", "test-secret-that-is-longer-than-thirty-two-characters")


def test_unique_stable_opaque_aliases_and_two_purposes(tmp_path):
    p = tmp_path / "delivery.json"
    one = ad.ensure_account("google-sub-1001", p, CFG)
    again = ad.ensure_account("google-sub-1001", p, CFG)
    two = ad.ensure_account("google-sub-1002", p, CFG)
    assert one["aliases"] == again["aliases"]
    assert one["aliases"]["alerts"] != two["aliases"]["alerts"]
    assert one["aliases"]["alerts"] != one["aliases"]["contact"]
    assert all(x.endswith("@dealsniffers.com") for x in one["aliases"].values())
    assert all("google" not in x and "1001" not in x for x in one["aliases"].values())


def test_unconfigured_is_honestly_not_connected(tmp_path):
    p = tmp_path / "delivery.json"
    rec = ad.ensure_account("u1", p, ad.AliasConfig(None, None))
    assert rec["aliases"] == {"alerts": None, "contact": None}
    s = ad.status("u1", "alerts", p, ad.AliasConfig(None, None))
    assert s["state"] == "NOT CONNECTED" and s["address"] is None


def test_domain_configuration_alone_never_claims_connected(tmp_path):
    p = tmp_path / "delivery.json"
    rec = ad.ensure_account("u1", p, CFG)
    s = ad.status("u1", "alerts", p, CFG)
    assert s["address"] == rec["aliases"]["alerts"]
    assert s["state"] == "NOT CONNECTED" and "has not produced a receipt" in s["detail"]
    ad.record_inbound_receipt("u1", "alerts", s["address"], "provider-message-7", "2026-10-13T05:00:00Z", p)
    live = ad.status("u1", "alerts", p, CFG)
    assert live["state"] == "LIVE CONNECTED" and "2026-10-13" in live["detail"]
    assert ad.status("u1", "contact", p, CFG)["state"] == "NOT CONNECTED"


def test_email_stays_disabled_until_matching_address_is_verified(tmp_path):
    p = tmp_path / "delivery.json"
    ad.ensure_account("u1", p, CFG)
    pending = ad.set_notification_preferences("u1", "michael@example.com", True, "instant", ["bid_changed", "closing_soon"], p)
    assert pending["notification_email_verified"] is False
    assert pending["notifications"] == {"email_enabled": False, "cadence": "instant", "events": ["bid_changed", "closing_soon"]}
    ad.record_email_verified("u1", "michael@example.com", "mail-provider-88", "2026-10-13T05:01:00Z", p)
    enabled = ad.set_notification_preferences("u1", "michael@example.com", True, "instant", ["bid_changed"], p)
    assert enabled["notifications"]["email_enabled"] is True
    changed = ad.set_notification_preferences("u1", "new@example.com", True, path=p)
    assert changed["notification_email_verified"] is False and changed["notifications"]["email_enabled"] is False


def test_no_source_password_or_alias_secret_is_persisted(tmp_path):
    p = tmp_path / "delivery.json"
    ad.ensure_account("u1", p, CFG)
    text = p.read_text()
    assert CFG.secret not in text
    assert "password" not in text.lower() and "source_credentials" not in text


def test_validation_and_provenance_are_required(tmp_path):
    p = tmp_path / "delivery.json"
    rec = ad.ensure_account("u1", p, CFG)
    with pytest.raises(ValueError):
        ad.set_notification_preferences("u1", "bad address", True, path=p)
    with pytest.raises(ValueError):
        ad.record_inbound_receipt("u1", "alerts", "wrong@dealsniffers.com", "receipt", "now", p)
    with pytest.raises(ValueError):
        ad.record_inbound_receipt("u1", "alerts", rec["aliases"]["alerts"], "", "now", p)
    assert json.loads(p.read_text())["schema"] == 1

