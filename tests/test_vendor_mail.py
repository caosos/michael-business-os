from __future__ import annotations

import json
from datetime import datetime, timezone
from email.message import EmailMessage

import pytest

from operator_ui import accounts, local_deal_sources, vendor_deals
from operator_ui.vendor_mail import (QuarantineStore, VendorMailError,
                                     VendorMailPipeline, VendorRegistry,
                                     dkim_authenticated_sender,
                                     reviewed_import_payload)


VENDOR = accounts.google_account("vendor-google-subject", "offers@conwaybutcher.example", "Conway Butcher")
NOW = "2026-10-13T18:00:00Z"


def message(message_id="<deal-100@example>", sender="offers@conwaybutcher.example", price="1.99") -> bytes:
    msg = EmailMessage()
    msg["From"] = f"Conway Butcher <{sender}>"
    msg["To"] = "vendors@dealsniffers.com"
    msg["Message-ID"] = message_id
    msg["Subject"] = "Today's ground beef deal"
    msg["Authentication-Results"] = "mx.dealsniffers.com; dkim=pass header.d=conwaybutcher.example"
    msg.set_content(f"""DEALSNIFFER DEAL
Title: Fresh ground beef
Category: Meat & groceries
Deal Price: {price}
Regular Price: 4.99
Unit: per pound
Location: Conway, AR 72032
Availability: 100 pounds while supplies last
Observed At: 2026-10-13T17:55:00Z
Starts On: 2026-10-13
Expires On: 2026-10-14
Description: Fresh 80/20 ground beef
Terms: Limit 10 pounds per customer
Original URL: https://conwaybutcher.example/specials/beef
Photo URL: https://conwaybutcher.example/images/beef.jpg
""")
    return msg.as_bytes()


@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    registry = VendorRegistry(tmp_path / "vendors.json")
    registry.register_verified(
        "conway_butcher", "Conway Family Butcher", "Conway, AR 72032",
        "offers@conwaybutcher.example", VENDOR, verified_at=NOW,
        proof_ref="onboarding-receipt-1", authority_attested=True,
        contact_permission=True, freshness_commitment=True,
    )
    offers = vendor_deals.Store(tmp_path / "vendor-deals.jsonl")
    quarantine = QuarantineStore(tmp_path / "quarantine.jsonl")
    return VendorMailPipeline(registry, offers, quarantine), offers, quarantine


def test_verified_sender_mail_becomes_review_pending_with_exact_provenance(pipeline):
    worker, offers, _ = pipeline
    raw = message()
    result = worker.process(raw, received_at=NOW, provider="test_adapter", receipt_id="receipt-100",
                            authenticated_sender="offers@conwaybutcher.example")
    assert result.state == "REVIEW_PENDING" and result.duplicate is False
    route = type("Route", (), {"storage_key": VENDOR.storage_key, "user_id": "vendor"})()
    rows = offers.recent(account=route)
    assert len(rows) == 1
    row = rows[0]
    assert row["published"] is False and row["verified"] is False
    assert row["offer"] == {
        "title": "Fresh ground beef", "category": "Meat & groceries",
        "description": "Fresh 80/20 ground beef", "deal_price_usd": 1.99,
        "regular_price_usd": 4.99, "unit": "per pound", "starts_on": "2026-10-13",
        "expires_on": "2026-10-14", "availability": "100 pounds while supplies last",
        "terms": "Limit 10 pounds per customer", "source_url": "https://conwaybutcher.example/specials/beef",
        "photo_url": "https://conwaybutcher.example/images/beef.jpg", "observed_at": "2026-10-13T17:55:00Z",
    }
    assert row["provenance"]["receipt_id"] == "receipt-100"
    assert row["provenance"]["authenticated_sender"] == "offers@conwaybutcher.example"
    assert len(row["provenance"]["message_sha256"]) == 64


def test_unknown_or_unauthenticated_sender_is_quarantined_and_never_written(pipeline):
    worker, offers, quarantine = pipeline
    unknown = worker.process(message(sender="stranger@example.net"), received_at=NOW, provider="test",
                             receipt_id="q-1", authenticated_sender="stranger@example.net")
    spoofed = worker.process(message(message_id="<deal-101@example>"), received_at=NOW, provider="test",
                             receipt_id="q-2", authenticated_sender=None)
    assert unknown.reason == "UNKNOWN_OR_UNVERIFIED_SENDER"
    assert spoofed.reason == "AUTHENTICATION_UNVERIFIED"
    route = type("Route", (), {"storage_key": VENDOR.storage_key, "user_id": "vendor"})()
    assert offers.recent(account=route) == []
    lines = [json.loads(line) for line in quarantine.path.read_text().splitlines()]
    assert len(lines) == 2 and all(row["published"] is False for row in lines)
    assert all("Fresh ground beef" not in json.dumps(row) for row in lines)


def test_message_id_and_offer_identity_deduplicate(pipeline):
    worker, offers, _ = pipeline
    first = worker.process(message(), received_at=NOW, provider="test", receipt_id="r-1",
                           authenticated_sender="offers@conwaybutcher.example")
    replay = worker.process(message(), received_at=NOW, provider="test", receipt_id="r-2",
                            authenticated_sender="offers@conwaybutcher.example")
    same_offer_new_message = worker.process(message(message_id="<deal-101@example>"), received_at=NOW,
                                            provider="test", receipt_id="r-3",
                                            authenticated_sender="offers@conwaybutcher.example")
    assert first.state == "REVIEW_PENDING"
    assert replay.state == same_offer_new_message.state == "DUPLICATE"
    route = type("Route", (), {"storage_key": VENDOR.storage_key, "user_id": "vendor"})()
    assert len(offers.recent(account=route)) == 1


def test_malformed_verified_mail_goes_to_quarantine(pipeline):
    worker, offers, quarantine = pipeline
    bad = message().replace(b"Deal Price: 1.99", b"Deal Price: not-a-price")
    result = worker.process(bad, received_at=NOW, provider="test", receipt_id="bad-1",
                            authenticated_sender="offers@conwaybutcher.example")
    assert result.state == "QUARANTINED" and result.reason == "MALFORMED_DEAL"
    assert "MALFORMED_DEAL" in quarantine.path.read_text()


def test_sender_can_belong_to_only_one_verified_customer_account(tmp_path):
    registry = VendorRegistry(tmp_path / "vendors.json")
    registry.register_verified("vendor_one", "One", "Conway, AR", "sales@example.com", VENDOR,
                               verified_at=NOW, proof_ref="proof-1", authority_attested=True,
                               contact_permission=True, freshness_commitment=True)
    other = accounts.google_account("other-subject", "other@example.com")
    with pytest.raises(VendorMailError, match="another vendor/customer account"):
        registry.register_verified("vendor_two", "Two", "Conway, AR", "sales@example.com", other,
                                   verified_at=NOW, proof_ref="proof-2", authority_attested=True,
                                   contact_permission=True, freshness_commitment=True)


def test_existing_read_only_reader_contract_and_dkim_gate(pipeline):
    worker, _, _ = pipeline

    class Reader:
        def messages(self, since):
            assert since == datetime(2026, 10, 12, tzinfo=timezone.utc)
            yield message()

    results = worker.import_reader(Reader(), datetime(2026, 10, 12, tzinfo=timezone.utc), provider="imap",
                                   authentication=dkim_authenticated_sender,
                                   clock=lambda: datetime(2026, 10, 13, 18, tzinfo=timezone.utc))
    assert [result.state for result in results] == ["REVIEW_PENDING"]


def test_review_mapping_reuses_local_deal_normalizer_and_keeps_photo(pipeline):
    worker, offers, _ = pipeline
    worker.process(message(), received_at=NOW, provider="test", receipt_id="r-1",
                   authenticated_sender="offers@conwaybutcher.example")
    route = type("Route", (), {"storage_key": VENDOR.storage_key, "user_id": "vendor", "audit_actor": "vendor"})()
    row = offers.recent(account=route)[0]
    payload = reviewed_import_payload(row, imported_at="2026-10-13T18:05:00Z")
    imported = local_deal_sources.normalize(payload, "2026-10-13T18:05:00Z", "import-mail-100", account=route)
    card = local_deal_sources.card(imported)
    assert imported["state"] == "IMPORTED"
    assert card["image"] == "https://conwaybutcher.example/images/beef.jpg"
    assert card["price"] == 1.99 and card["unit"] == "per pound"
