from __future__ import annotations

import json

import pytest

from operator_ui import mail_delivery as mail


ACCOUNT_A = "a" * 32
ACCOUNT_B = "b" * 32
CONFIG = mail.MailConfig(
    "dealsniffers.com",
    b"alias-secret-is-at-least-thirty-two-bytes-long",
    b"receipt-secret-is-at-least-thirty-two-bytes-long",
)
NOW = 1791874800


def envelope(**updates) -> bytes:
    event = {
        "version": 1,
        "event": "inbound.received",
        "provider": "adapter_test",
        "receipt_id": "provider-receipt-1",
        "occurred_at": "2026-10-13T06:20:00Z",
        "recipient": mail.alias_for(ACCOUNT_A, "alerts", CONFIG),
        "test": True,
    }
    event.update(updates)
    return json.dumps(event, separators=(",", ":"), sort_keys=True).encode()


def signed(store, body, timestamp=NOW):
    return store.verifier.sign_for_test(body, timestamp)


def test_aliases_are_stable_separate_and_do_not_expose_account_ids(tmp_path):
    store = mail.MailDeliveryStore(tmp_path / "mail.json", CONFIG)
    a = store.register_account(ACCOUNT_A)
    b = store.register_account(ACCOUNT_B)
    assert a["state"] == "NOT CONNECTED"
    assert a["aliases"] == store.register_account(ACCOUNT_A)["aliases"]
    assert a["aliases"]["alerts"] != a["aliases"]["contact"]
    assert a["aliases"]["alerts"] != b["aliases"]["alerts"]
    assert ACCOUNT_A not in json.dumps(a)
    assert ACCOUNT_B not in json.dumps(b)
    assert a["route_ref"].startswith("acct_")


def test_mailbox_is_not_connected_until_valid_signed_inbound_proof(tmp_path):
    store = mail.MailDeliveryStore(tmp_path / "mail.json", CONFIG)
    store.register_account(ACCOUNT_A)
    assert store.mailbox_status(ACCOUNT_A, "alerts") == {
        "purpose": "alerts",
        "address": mail.alias_for(ACCOUNT_A, "alerts", CONFIG),
        "state": "NOT CONNECTED",
        "last_proven_at": None,
        "test": None,
    }
    body = envelope()
    receipt, routed = store.accept_signed_receipt(body, NOW, signed(store, body), now=NOW)
    assert routed == ACCOUNT_A
    assert receipt.event == "inbound.received" and receipt.duplicate is False and receipt.test is True
    assert ACCOUNT_A not in repr(receipt)
    assert store.mailbox_status(ACCOUNT_A, "alerts")["state"] == "LIVE CONNECTED"
    assert store.mailbox_status(ACCOUNT_A, "contact")["state"] == "NOT CONNECTED"


def test_bad_expired_and_extra_field_receipts_are_rejected_without_state_change(tmp_path):
    store = mail.MailDeliveryStore(tmp_path / "mail.json", CONFIG)
    store.register_account(ACCOUNT_A)
    body = envelope()
    with pytest.raises(mail.ReceiptError, match="signature"):
        store.accept_signed_receipt(body, NOW, "v1=" + "0" * 64, now=NOW)
    with pytest.raises(mail.ReceiptError, match="acceptance window"):
        store.accept_signed_receipt(body, NOW, signed(store, body), now=NOW + 301)
    extra = envelope(subject="a message body must not be accepted")
    with pytest.raises(mail.ReceiptError, match="unsupported fields"):
        store.accept_signed_receipt(extra, NOW, signed(store, extra), now=NOW)
    assert store.mailbox_status(ACCOUNT_A, "alerts")["state"] == "NOT CONNECTED"


def test_unregistered_or_wrong_domain_alias_cannot_route(tmp_path):
    store = mail.MailDeliveryStore(tmp_path / "mail.json", CONFIG)
    store.register_account(ACCOUNT_A)
    unknown = envelope(recipient="alerts-aaaaaaaaaaaaaaaaaaaa@dealsniffers.com")
    with pytest.raises(mail.ReceiptError, match="not registered"):
        store.accept_signed_receipt(unknown, NOW, signed(store, unknown), now=NOW)
    wrong = envelope(recipient=mail.alias_for(ACCOUNT_A, "alerts", CONFIG).replace("dealsniffers.com", "evil.test"))
    with pytest.raises(mail.ReceiptError, match="not a DealSniffer alias"):
        store.accept_signed_receipt(wrong, NOW, signed(store, wrong), now=NOW)


def test_duplicate_provider_receipt_is_idempotent_and_routes_identically(tmp_path):
    store = mail.MailDeliveryStore(tmp_path / "mail.json", CONFIG)
    store.register_account(ACCOUNT_A)
    body = envelope()
    signature = signed(store, body)
    first, route1 = store.accept_signed_receipt(body, NOW, signature, now=NOW)
    second, route2 = store.accept_signed_receipt(body, NOW, signature, now=NOW)
    assert first.duplicate is False and second.duplicate is True
    assert route1 == route2 == ACCOUNT_A
    doc = json.loads((tmp_path / "mail.json").read_text())
    assert len(doc["receipts"]) == 1

    collision = envelope(test=False)
    with pytest.raises(mail.ReceiptError, match="reused for a different event"):
        store.accept_signed_receipt(collision, NOW, signed(store, collision), now=NOW)


def test_delivery_attempt_stays_not_active_until_signed_success_receipt(tmp_path):
    store = mail.MailDeliveryStore(tmp_path / "mail.json", CONFIG)
    request = store.create_delivery_attempt(
        ACCOUNT_A, "Michael+Deals@example.com", test=True,
        now="2026-10-13T06:19:00Z", token="dlv_" + "x" * 40,
    )
    assert store.notification_status(ACCOUNT_A)["state"] == "NOT ACTIVE"
    body = envelope(
        event="delivery.delivered", receipt_id="delivered-501",
        recipient=None, delivery_token=request.delivery_token,
    )
    event = json.loads(body)
    event.pop("recipient")
    body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
    receipt, routed = store.accept_signed_receipt(body, NOW, signed(store, body), now=NOW)
    assert routed == ACCOUNT_A and receipt.event == "delivery.delivered"
    assert store.notification_status(ACCOUNT_A) == {
        "state": "ACTIVE", "last_proven_at": "2026-10-13T06:20:00Z", "test": True,
    }


def test_failed_delivery_is_recorded_but_never_activates_notifications(tmp_path):
    store = mail.MailDeliveryStore(tmp_path / "mail.json", CONFIG)
    request = store.create_delivery_attempt(
        ACCOUNT_A, "michael@example.com", test=False,
        now="2026-10-13T06:19:00Z", token="dlv_" + "y" * 40,
    )
    event = {
        "version": 1, "event": "delivery.failed", "provider": "provider_a",
        "receipt_id": "failed-1", "occurred_at": "2026-10-13T06:20:00Z",
        "delivery_token": request.delivery_token, "test": False,
    }
    body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
    accepted, _ = store.accept_signed_receipt(body, NOW, signed(store, body), now=NOW)
    assert accepted.event == "delivery.failed"
    assert store.notification_status(ACCOUNT_A)["state"] == "NOT ACTIVE"


def test_delivery_receipt_test_flag_must_match_registered_attempt(tmp_path):
    store = mail.MailDeliveryStore(tmp_path / "mail.json", CONFIG)
    request = store.create_delivery_attempt(
        ACCOUNT_A, "michael@example.com", test=True,
        now="2026-10-13T06:19:00Z", token="dlv_" + "q" * 40,
    )
    event = {
        "version": 1, "event": "delivery.delivered", "provider": "provider_a",
        "receipt_id": "mismatch-1", "occurred_at": "2026-10-13T06:20:00Z",
        "delivery_token": request.delivery_token, "test": False,
    }
    body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
    with pytest.raises(mail.ReceiptError, match="does not match"):
        store.accept_signed_receipt(body, NOW, signed(store, body), now=NOW)
    assert store.notification_status(ACCOUNT_A)["state"] == "NOT ACTIVE"


def test_store_contains_no_raw_tokens_destinations_signatures_or_secrets(tmp_path):
    store = mail.MailDeliveryStore(tmp_path / "mail.json", CONFIG)
    store.register_account(ACCOUNT_A)
    request = store.create_delivery_attempt(
        ACCOUNT_A, "private.destination@example.com", token="dlv_" + "z" * 40,
        now="2026-10-13T06:19:00Z",
    )
    body = envelope()
    signature = signed(store, body)
    store.accept_signed_receipt(body, NOW, signature, now=NOW)
    persisted = (tmp_path / "mail.json").read_text()
    assert request.delivery_token not in persisted
    assert request.destination not in persisted
    assert signature not in persisted
    assert CONFIG.alias_secret.decode() not in persisted
    assert CONFIG.receipt_secret.decode() not in persisted
    assert "subject" not in persisted and "body" not in persisted


def test_config_requires_named_secret_environment_variables_and_redacts_repr():
    env = {
        "MBOS_INTAKE_MAIL_DOMAIN": "dealsniffers.com",
        "MBOS_INTAKE_ALIAS_SECRET_ENV": "ALIAS_SECRET",
        "MBOS_MAIL_RECEIPT_SECRET_ENV": "RECEIPT_SECRET",
        "ALIAS_SECRET": "a" * 32,
        "RECEIPT_SECRET": "b" * 32,
    }
    config = mail.MailConfig.from_env(env)
    assert config.alias_domain == "dealsniffers.com"
    assert "a" * 32 not in repr(config) and "b" * 32 not in repr(config)
    with pytest.raises(ValueError, match="required"):
        mail.MailConfig.from_env({})
