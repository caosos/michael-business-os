"""F-24 (G-16 F-72..F-77): My numbers hardening, through the real HTTP server and lane D's real UI login."""

from __future__ import annotations

import re

import pytest

from operator_ui import numbers_view, ux
from operator_ui.ux import InputError
from tests.conftest import PIN
from tests.lane_d.test_my_numbers_f22 import current, position, post, req, ui_least, ui_role  # noqa: F401

pytestmark = pytest.mark.usefixtures("rtd")


def test_replay_reports_the_receipt_not_the_request(rtd, ui_least):  # F-72
    p0 = position(rtd)[0]
    post(ui_least, "/numbers/capital", kind="fund", amount="7", nonce="replayF240")
    s, loc, _ = post(ui_least, "/numbers/capital", kind="fund", amount="900", nonce="replayF240")
    assert s == 303 and position(rtd)[0] - p0 == 7
    assert "900" not in loc and "already" in loc and "7.00" in loc and "Nothing new" in loc


def test_zero_renders_as_zero(rtd, ui_least):  # F-74
    post(ui_least, "/numbers/mission", weekly_target_usd="0", hours_available="0")
    body = req(ui_least, "GET", "/numbers")[2]
    assert re.findall(r"name='(?:weekly_target_usd|hours_available)' inputmode='decimal' value='([^']*)'", body) == ["0", "0"]


@pytest.mark.parametrize("k", ["csrf", "pin", "nonce"])
def test_non_ascii_secrets_are_a_refusal_page(rtd, ui_least, k):  # F-73
    s, _, body = post(ui_least, "/numbers/capital", kind="fund", amount="1", **{k: "é٣"})
    assert s == 200 and "Not saved" in body


def test_non_ascii_pin_on_the_notes_gate_does_not_crash(ui_least):  # F-73
    with pytest.raises(InputError):
        ui_least.pin_gate.check("é", PIN, "no.")


@pytest.mark.parametrize("amt", ["٣٠٠", "９", "$$5", "1,5,0,0", "12,34", "1,5000", "$ 5", "5$"])
def test_strict_amounts_refused(rtd, ui_least, amt):  # F-75
    s, _, body = post(ui_least, "/numbers/capital", kind="fund", amount=amt)
    assert s == 200 and "Not saved" in body


@pytest.mark.parametrize("raw,want", [("$1,500.50", "1500.50"), ("1,500", "1500"), ("12.5", "12.5"), ("1500", "1500")])
def test_good_amounts_parse(raw, want):
    assert str(numbers_view.parse_amount(raw, "A", cap=numbers_view.MAX_USD, required=True)) == want


def test_cumulative_cap_and_typed_confirmation(rtd, ui_least, tmp_path, monkeypatch):  # F-76
    f = tmp_path / "limits.json"
    f.write_text('{"max_total_funded_usd": 100000}')
    monkeypatch.setattr(numbers_view, "LIMITS_FILE", f)
    p0 = position(rtd)[0]
    s, _, body = post(ui_least, "/numbers/capital", kind="fund", amount="2500")
    assert s == 200 and "type FUND 2500.00" in body and position(rtd)[0] == p0
    s, _, body = post(ui_least, "/numbers/capital", kind="fund", amount="2500", confirm="fund 2400.00")
    assert s == 200 and "Not saved" in body and position(rtd)[0] == p0
    assert post(ui_least, "/numbers/capital", kind="fund", amount="2500", confirm="FUND 2500.00")[0] == 303
    assert position(rtd)[0] - p0 == 2500
    assert post(ui_least, "/numbers/capital", kind="fund", amount="2000")[0] == 303  # at the threshold: no confirm
    f.write_text('{"max_total_funded_usd": 100}')
    s, _, body = post(ui_least, "/numbers/capital", kind="fund", amount="1")
    assert s == 200 and "over your limit of $100" in body


def test_default_cumulative_cap_is_5000(rtd, ui_least):
    assert numbers_view.limits()["max_total_funded_usd"] == 5000
    s, _, body = post(ui_least, "/numbers/capital", kind="fund", amount="10000000", confirm="FUND 10000000.00")
    assert s == 200 and "over your limit" in body


def test_pin_gate_locks_after_five_failures_then_unlocks():
    t = [0.0]
    g = ux.PinGate(clock=lambda: t[0])
    for _ in range(4):
        with pytest.raises(InputError, match="tries left"):
            g.check("x", PIN, "no.")
    with pytest.raises(InputError, match="locked for 5 minutes"):
        g.check("x", PIN, "no.")
    with pytest.raises(InputError, match="locked"):
        g.check(PIN, PIN, "no.")  # the right PIN is refused while locked
    t[0] = 301
    g.check(PIN, PIN, "no.")
    assert g.fails == 0


def test_pin_gate_success_resets_the_count():
    g = ux.PinGate()
    for _ in range(4):
        with pytest.raises(InputError):
            g.check("x", PIN, "no.")
    g.check(PIN, PIN, "no.")
    with pytest.raises(InputError, match="tries left"):
        g.check("x", PIN, "no.")


def test_locked_gate_is_shown_to_michael(rtd, ui_least):
    for _ in range(5):
        post(ui_least, "/numbers/capital", kind="fund", amount="1", pin="0000")
    s, _, body = post(ui_least, "/numbers/capital", kind="fund", amount="1")
    assert s == 200 and "locked" in body
    assert "PIN entry is locked" in req(ui_least, "GET", "/numbers")[2]
