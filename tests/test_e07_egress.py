"""E-07: egress allow-list per adapter/effector as policy data + fail-closed checker."""
from __future__ import annotations

import copy
import json

import pytest

from mbos_governance import PolicyStore, PolicyUnavailable
from mbos_governance.egress import check_catalog, effective_allow
from mbos_governance.hooks import render_egress
from mbos_governance.panic import PanicState

RUNNING = PanicState("RUNNING")


def test_shipped_catalog_is_clean_and_fully_disabled(env):
    data = PolicyStore(env.policy_path).current().data
    cat = data["egress"]["catalog"]
    assert {e["id"] for e in cat} == {"adapter:ebay_browse", "adapter:gsa_auctions", "adapter:trash_nothing"}
    assert all(e["enabled"] is False and e["methods"] == ["GET"] and e["port"] == 443 for e in cat)
    assert check_catalog(data) == [] and effective_allow(data, RUNNING) == {}      # wave one: no egress at all


@pytest.mark.parametrize("host,code", [
    ("*.ebay.com", "not an exact FQDN"), ("10.0.0.5", "IP literal"), ("::1", "IP literal"),
    ("db.internal", "local/internal"), ("printer.local", "local/internal"), ("localhost", "not an exact FQDN"),
    ("API.EBAY.COM", "lowercase"), ("ebay", "not an exact FQDN"), ("api.ebay.com.", "lowercase"),
])
def test_bad_hosts_make_the_policy_unavailable(env, host, code):
    env.policy_edit(lambda d: d["egress"]["catalog"][0].__setitem__("hosts", [host]))
    with pytest.raises(PolicyUnavailable, match=code):
        PolicyStore(env.policy_path).current()


@pytest.mark.parametrize("mutate,code", [
    (lambda e: e.__setitem__("methods", ["GET", "POST"]), "read-only"),
    (lambda e: e.__setitem__("owner", "agent-99-ghost"), "not a known agent"),
    (lambda e: e.__setitem__("kind", "effector"), "id prefix"),
])
def test_entry_rules(env, mutate, code):
    env.policy_edit(lambda d: mutate(d["egress"]["catalog"][1]))
    with pytest.raises(PolicyUnavailable, match=code):
        PolicyStore(env.policy_path).current()


def test_duplicate_ids_refused(env):
    env.policy_edit(lambda d: d["egress"]["catalog"].append(copy.deepcopy(d["egress"]["catalog"][0])))
    with pytest.raises(PolicyUnavailable, match="duplicate id"):
        PolicyStore(env.policy_path).current()


@pytest.mark.parametrize("mutate", [
    lambda e: e.__setitem__("enabled", True),          # wave one: nothing may be enabled
    lambda e: e.__setitem__("port", 80),
    lambda e: e.__setitem__("scheme", "http"),
])
def test_wave_one_schema_pins(env, mutate):
    env.policy_edit(lambda d: mutate(d["egress"]["catalog"][0]))
    with pytest.raises(PolicyUnavailable, match="schema"):
        PolicyStore(env.policy_path).current()


def test_effective_allow_logic_beyond_wave_one():
    """Generator semantics for when enabling is allowed: enabled entries only, L1/L3/unreadable remove them."""
    data = {"agent_grants": {"agent-02-opportunity": [], "agent-06-communications": []},
            "egress": {"allow": {}, "catalog": [
                {"id": "adapter:a", "owner": "agent-02-opportunity", "kind": "source_adapter", "hosts": ["api.gsa.gov"],
                 "methods": ["GET"], "enabled": True},
                {"id": "adapter:b", "owner": "agent-02-opportunity", "kind": "source_adapter", "hosts": ["api.ebay.com"],
                 "methods": ["GET"], "enabled": False},
                {"id": "effector:sms", "owner": "agent-06-communications", "kind": "effector", "hosts": ["api.twilio.com"],
                 "methods": ["POST"], "enabled": True}]}}
    assert check_catalog(data) == []
    assert effective_allow(data, RUNNING) == {"agent-02-opportunity": ["api.gsa.gov"], "agent-06-communications": ["api.twilio.com"]}
    assert effective_allow(data, PanicState("RUNNING", frozen_agents={"agent-06-communications": {}})) == {
        "agent-02-opportunity": ["api.gsa.gov"]}
    assert effective_allow(data, PanicState("FROZEN")) == {}
    assert effective_allow(data, PanicState("FROZEN", readable=False, error="x")) == {}
    doc = render_egress(data, RUNNING)
    assert doc["allow"]["agent-02-opportunity"] == ["api.gsa.gov"] and len(doc["catalog"]) == 3


def test_rendered_file_carries_catalog_and_empty_allow(env):
    doc = render_egress(PolicyStore(env.policy_path).current().data, env.panic.read())
    assert doc["default"] == "deny" and doc["allow"] == {} and not doc["deny_all"]
    assert {e["id"] for e in doc["catalog"]} == {"adapter:ebay_browse", "adapter:gsa_auctions", "adapter:trash_nothing"}
    json.dumps(doc)
