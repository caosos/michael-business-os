"""Live My Bids state transitions from authenticated evidence; no bid placement."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from operator_ui import bid_state_watch as bw


def obs(evidence, **updates):
    values = dict(
        listing_id="hibid:lot-34", source="Wooley / HiBid", title="Lot 34 County Line 32-ton log splitter",
        url="https://wooleyauctioneers.hibid.com/lot/34", state="WINNING",
        observed_at="2026-10-13T17:10:00-05:00", evidence_kind="AUTHORIZED_SESSION",
        evidence_id=evidence, current_bid="800", user_max_bid="800", next_required_bid="825",
        closes_at="2026-10-13T18:10:00-05:00", adapter="hibid_authorized_session_v1",
    )
    values.update(updates)
    return bw.BidObservation(**values)


def test_winning_to_outbid_is_receipted_and_queues_immediate_high_priority_notification(tmp_path):
    store = bw.BidWatchStore(tmp_path / "state.json")
    first = store.apply(obs("session-snapshot-1"))
    assert first["watch"]["state"] == "WINNING"
    assert first["watch"]["current_bid"] == "800.00"
    assert first["watch"]["user_max_bid"] == "800.00"
    assert first["watch"]["next_required_bid"] == "825.00"
    assert first["watch"]["last_verified_at"] == "2026-10-13T22:10:00Z"

    changed = store.apply(obs("session-snapshot-2", state="OUTBID", current_bid="825", next_required_bid="850",
                              observed_at="2026-10-13T17:11:00-05:00"))
    assert [r["event"] for r in changed["receipts"]] == ["BID_STATE_CHANGED", "BID_NOTIFICATION_QUEUED"]
    notice = changed["receipts"][1]
    assert notice["details"]["delivery"] == "IMMEDIATE"
    assert notice["details"]["delivery_state"] == "QUEUED_NOT_DELIVERED"
    assert notice["details"]["priority"] == "HIGH"
    assert notice["details"]["current_bid"] == "825.00" and notice["details"]["next_required_bid"] == "850.00"


def test_soft_close_extension_updates_close_and_is_receipted(tmp_path):
    store = bw.BidWatchStore(tmp_path / "state.json")
    store.apply(obs("snapshot-a", observed_at="2026-10-13T18:07:00-05:00"))
    extended = store.apply(obs("snapshot-b", observed_at="2026-10-13T18:09:00-05:00",
                               closes_at="2026-10-13T18:15:00-05:00"))
    assert extended["watch"]["closes_at"] == "2026-10-13T23:15:00Z"
    assert [r["event"] for r in extended["receipts"]] == ["BID_SOFT_CLOSE_EXTENDED", "BID_NOTIFICATION_QUEUED"]
    assert extended["poll"] == {"interval_seconds": 30, "priority": "HIGH", "reason": "final fifteen minutes"}


def test_won_and_lost_are_distinct_terminal_states(tmp_path):
    for state, expected in (("ENDED_WON", "ENDED_WON"), ("ENDED_LOST", "ENDED_LOST")):
        store = bw.BidWatchStore(tmp_path / f"{state}.json")
        store.apply(obs("one"))
        result = store.apply(obs("two", state=state, observed_at="2026-10-13T18:16:00-05:00"))
        assert result["watch"]["state"] == expected
        assert result["poll"] == {"interval_seconds": None, "priority": "NONE", "reason": "auction ended"}
        assert result["receipts"][1]["details"]["priority"] == "HIGH"


def test_final_fifteen_minute_polling_policy():
    watch = {"state": "WINNING", "closes_at": "2026-10-13T23:10:00Z"}
    policy = bw.poll_policy(watch, datetime.fromisoformat("2026-10-13T23:00:00+00:00"))
    assert (policy.interval_seconds, policy.priority, policy.reason) == (30, "HIGH", "final fifteen minutes")
    final_two = bw.poll_policy(watch, datetime.fromisoformat("2026-10-13T23:08:30+00:00"))
    assert final_two.interval_seconds == 15 and final_two.priority == "HIGH"


def test_duplicate_evidence_is_idempotent_and_old_observation_is_rejected(tmp_path):
    store = bw.BidWatchStore(tmp_path / "state.json")
    store.apply(obs("same"))
    duplicate = store.apply(obs("same", state="OUTBID"))
    assert duplicate["duplicate"] is True and duplicate["receipts"] == []
    assert len(store.load()["receipts"]) == 2
    with pytest.raises(ValueError, match="older"):
        store.apply(obs("old", observed_at="2026-10-13T17:09:00-05:00"))


def test_authenticated_email_adapter_requires_auth_and_maps_states(tmp_path):
    event = {
        "authenticated": True, "listing_id": "hibid:lot-34", "source": "hibid", "title": "Lot 34",
        "url": "https://hibid.com/lot/34", "event": "outbid", "observed_at": "2026-10-13T17:30:00-05:00",
        "current_bid": 825, "next_required_bid": 850, "closes_at": "2026-10-13T18:10:00-05:00",
        "provenance": {"message_id": "msg-34-outbid"}, "adapter": "dkim_hibid_alert_v1",
    }
    converted = bw.authenticated_email_observation(event, user_max_bid=800)
    result = bw.BidWatchStore(tmp_path / "email.json").apply(converted)
    assert result["watch"]["state"] == "OUTBID" and result["watch"]["last_evidence_kind"] == "AUTHENTICATED_EMAIL"
    with pytest.raises(ValueError, match="not authenticated"):
        bw.authenticated_email_observation({**event, "authenticated": False})


def test_authorized_session_adapter_contract_and_no_secrets_are_persisted(tmp_path):
    class Adapter:
        adapter_name = "authorized-test"

        def observations(self, watches, now):
            assert watches == {}
            return [obs("authorized-1")]

    path = tmp_path / "state.json"
    results = bw.BidWatchStore(path).poll_adapter(Adapter(), datetime.fromisoformat("2026-10-13T17:10:00-05:00"))
    assert results[0]["watch"]["state"] == "WINNING"
    persisted = path.read_text()
    assert "password" not in persisted.lower() and "cookie" not in persisted.lower() and "token" not in persisted.lower()
    assert "hibid_authorized_session_v1" in persisted


def test_receipts_are_append_only_and_store_is_private(tmp_path):
    path = tmp_path / "state.json"
    store = bw.BidWatchStore(path)
    store.apply(obs("a"))
    store.apply(obs("b", current_bid=810, next_required_bid=825, observed_at="2026-10-13T17:12:00-05:00"))
    doc = json.loads(path.read_text())
    assert [r["seq"] for r in doc["receipts"]] == list(range(1, len(doc["receipts"]) + 1))
    assert path.stat().st_mode & 0o777 == 0o600
