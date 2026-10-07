"""The vendored contracts must be byte-identical to Agent 01's freeze (1269405)."""

import hashlib
from importlib import resources

PINNED = {
    "item.schema.json": "c5a806f6ce98265dc697f53ec564b5c326d68d3eeed120d13c5caf2e40ee3ad4",
    "provenance.schema.json": "15db68a4c6ef28d442209cd35e45970330653e7dff76ce5431bd8b05ec807b4c",
    "receipt.schema.json": "c6a55d47583541aef839bc66f5ecf07dcca187d0325b64b380a3a1bf52f155f9",
    "vendor/agent-03/opportunity.schema.json": "0633bc58ae987e2b0596c343b404b8f982fcee7c6d02521d9bd311c268cf5797",
    "vendor/agent-03/scorecard.schema.json": "a6718390616d3a0b29c6e4454a92c8e6efb54580d69f7b6716fb3841e17abb8d",
    "vendor/agent-03/service-job.schema.json": "9e1fddc22fb50324999a4dda683d8268458a424bb462463a6933c3e5001d1506",
}


def test_vendored_contracts_match_freeze():
    root = resources.files("mbos_discovery") / "contracts" / "v1.0.0"
    for rel, digest in PINNED.items():
        data = root.joinpath(*rel.split("/")).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, f"{rel} drifted from the frozen contract"
