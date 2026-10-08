import copy
import json

import pytest

from mbos import campaign, valuation
from mbos.contracts.schemas import ContractViolation, contracts_dir

EX = contracts_dir() / "examples"


def load(p):
    return json.loads((EX / p).read_text())


def test_examples_validate():
    campaign.validate(load("campaign/trailer-wanted.example.json"))
    valuation.validate(load("valuation/mower.example.json"))
    valuation.validate(load("valuation/home-unknown.example.json"))


@pytest.mark.parametrize("mut,frag", [
    (lambda c: c["autonomy"].update(level="BOUNDED_AUTOPILOT"), "limits"),
    (lambda c: c["autonomy"].update(level="BOUNDED_AUTOPILOT", limits={"max_total_spend_usd": 100}), "required"),
    (lambda c: c["autonomy"].update(level="FULL_SEND"), "FULL_SEND"),
    (lambda c: c["criteria"].update(max_price_usd=-1), "minimum"),
    (lambda c: c.update(campaign_id="nope"), "does not match"),
    (lambda c: c["autonomy"].update(level="ASSISTED_DEAL", limits={"max_offer_usd": 900, "max_total_spend_usd": 1000}), "criteria.max_price_usd"),
    (lambda c: c.update(unexpected=1), "Additional"),
])
def test_campaign_rejects(mut, frag):
    c = load("campaign/trailer-wanted.example.json")
    mut(c)
    errs = campaign.errors(c)
    assert errs and any(frag in e for e in errs), errs


def test_autopilot_with_limits_is_valid_data_but_never_runnable():
    c = load("campaign/trailer-wanted.example.json")
    c["autonomy"] = {"level": "BOUNDED_AUTOPILOT", "limits": {"max_total_spend_usd": 600, "max_offer_usd": 500, "expires_at": "2026-12-01T00:00:00Z"}}
    assert campaign.errors(c) == []
    assert not campaign.may_run(c)
    c["autonomy"] = {"level": "ASSISTED_DEAL"}
    assert not campaign.may_run(c)
    c["autonomy"] = {"level": "WATCH_ONLY"}
    assert campaign.may_run(c)
    c["status"] = "PAUSED"
    assert not campaign.may_run(c)


@pytest.mark.parametrize("mut,frag", [
    (lambda v: v.pop("not_an_appraisal"), "not_an_appraisal"),
    (lambda v: v.update(not_an_appraisal=False), "True"),
    (lambda v: v.update(evidence=[]), "without evidence"),
    (lambda v: v["ranges"]["likely_sale"].update(low=900), "low > high"),
    (lambda v: v.update(confidence="high"), "high requires"),
    (lambda v: v["ranges"].pop("as_is"), "as_is"),
    (lambda v: v["ranges"].update(as_is={"low": 1}), "not valid"),
])
def test_valuation_rejects(mut, frag):
    v = load("valuation/mower.example.json")
    mut(v)
    errs = valuation.errors(v)
    assert errs and any(frag in e for e in errs), errs


def test_unknown_valuation_needs_a_reason_and_may_not_claim_confidence():
    v = load("valuation/home-unknown.example.json")
    v2 = copy.deepcopy(v); v2.pop("reason_unknown")
    assert any("reason_unknown" in e for e in valuation.errors(v2))
    v3 = copy.deepcopy(v); v3["confidence"] = "high"
    assert any("confidence" in e for e in valuation.errors(v3))


def test_validate_raises():
    with pytest.raises(ContractViolation):
        valuation.validate({})


def test_f63_nan_everywhere():
    c = load("campaign/trailer-wanted.example.json"); c["criteria"]["max_price_usd"] = float("nan")
    assert campaign.errors(c) and not campaign.may_run(c)
    v = load("valuation/mower.example.json"); v["ranges"]["likely_sale"]["high"] = float("inf")
    assert valuation.errors(v)


def test_f66_may_run_honours_expiry_and_tolerates_garbage():
    from datetime import datetime, timezone
    c = load("campaign/trailer-wanted.example.json")
    c["stop_conditions"]["expires_at"] = "2020-01-01T00:00:00Z"
    assert not campaign.may_run(c)
    c["stop_conditions"]["expires_at"] = "2099-01-01T00:00:00Z"
    assert campaign.may_run(c) and not campaign.may_run(c, now=datetime(2100, 1, 1, tzinfo=timezone.utc))
    for junk in ({}, None, [], "x", {"autonomy": 1}):
        assert campaign.may_run(junk) is False


def test_f67_valuation_ordering_confidence_and_appraisal_claims():
    v = load("valuation/mower.example.json"); v["ranges"]["fast_sale"] = {"low": 700, "high": 900}
    assert any("fast_sale" in e for e in valuation.errors(v))
    v = load("valuation/mower.example.json"); v["confidence"] = "high"; v["evidence"] = [{"kind": "sold_comp", "ref": "one"}]
    assert any("at least two" in e for e in valuation.errors(v))
    v["evidence"].append({"kind": "sold_comp", "ref": "two"})
    assert valuation.errors(v) == []
    for txt in ("Appraised at $500", "licensed appraisal attached", "appraisal value 500"):
        v = load("valuation/mower.example.json"); v["subject"]["description"] = txt
        assert any("appraisal" in e for e in valuation.errors(v)), txt
