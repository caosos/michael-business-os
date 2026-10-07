"""Reference stubs satisfy the lane Protocols; the placeholder scorer is replayable (AT-1/C22 shape)."""

import copy

from mbos import interfaces
from mbos.reference.fixture_adapter import FixtureNormalizer, FixtureSourceAdapter
from mbos.reference.governance import (
    DenyByDefaultPDP, DryRunEffector, LedgerLLMBudget, ReferenceGateway, TableKillSwitch, classify_capability,
)
from mbos.reference.notify import OutboxNotifier
from mbos.reference.placeholder_scorer import PlaceholderScorer
from mbos.workflows import _iso_duration
from tests.helpers.common import FIXTURE


def test_reference_stubs_implement_protocols():
    adapter = FixtureSourceAdapter(FIXTURE)
    assert isinstance(adapter, interfaces.SourceAdapter)
    assert isinstance(FixtureNormalizer(), interfaces.Normalizer)
    assert isinstance(PlaceholderScorer(), interfaces.Scorer)
    assert isinstance(DenyByDefaultPDP(), interfaces.PolicyDecisionPoint)
    assert isinstance(TableKillSwitch(), interfaces.KillSwitch)
    assert isinstance(DryRunEffector(), interfaces.Effector) and DryRunEffector.dry_run is True
    assert isinstance(ReferenceGateway(DryRunEffector(), TableKillSwitch()), interfaces.Gateway)
    assert isinstance(LedgerLLMBudget({}), interfaces.LLMBudget)
    assert isinstance(OutboxNotifier(), interfaces.Notifier)


def test_scorer_replay_is_deterministic():
    raws = FixtureSourceAdapter(FIXTURE).fetch()
    norm = FixtureNormalizer()
    for raw in raws:
        n = norm.normalize(raw)
        item = {"type": n.type, "economics": n.economics, "research": []}
        a, b = PlaceholderScorer().score(copy.deepcopy(item)), PlaceholderScorer().score(copy.deepcopy(item))
        assert a == b and a.inputs_hash.startswith("sha256:")


def test_pdp_never_delegates_in_mvp():
    for cap in ("comms.email.send", "money.payment.send", "publish.listing.create", "weird.thing"):
        d = DenyByDefaultPDP().decide({"capability": cap})
        assert d.tier == 0 and d.decision == "require_approval"
    assert classify_capability("weird.thing")[0] == "external_commitment"


def test_iso_durations():
    assert _iso_duration("PT24H").total_seconds() == 86400
    assert _iso_duration("P7D").days == 7
    assert _iso_duration("PT1M30S").total_seconds() == 90
