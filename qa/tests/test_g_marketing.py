"""G (owner 07) — G1 no publish/send without an approved ActionRequest; G2 every lead carries attribution;
G4 manual-assist packets carry content hash, prompt version and model in provenance.
(G3 review-request policy has no wave-one code path: no review requests are drafted yet.)"""
from mbos_qa import drafts


def test_g1_every_effector_call_traces_to_a_yes_on_the_same_payload(ran):
    executed = ran.store.receipts(type="ACTION_EXECUTED")
    assert executed
    for r in executed:
        appr = ran.store.get("approval", r["approval_id"])
        assert appr["decision"] == "YES" and appr["decider"] == "michael"
        assert appr["action_request_id"] == r["action_request_id"]
        assert appr["payload_hash_seen"] == r["payload_hash"]
    packets = {p.stem for p in (ran.workdir / "packets").glob("*.md")}
    assert packets == {r["action_request_id"] for r in executed}, "a packet exists without an approved request"


def test_g2_every_service_lead_has_attribution(ran):
    leads = [d for k, d in ran.store.all_documents() if k == "item" and d["opportunity_kind"] == "service_lead"]
    assert leads
    for item in leads:
        outs = [ran.store.get("outcome", o) for o in item.get("outcome_ids", [])]
        attr = [o for o in outs if o["kind"] == "lead_attributed"]
        assert attr and attr[0]["attribution"]["first_touch_source"]


def test_g4_packet_provenance_has_content_hash_prompt_version_and_model(ran):
    for r in ran.store.receipts(type="ACTION_EXECUTED"):
        areq = ran.store.get("action-request", r["action_request_id"])
        provs = [ran.store.find_provenance(p) for p in areq["provenance_ids"]]
        draft = [p for p in provs if p.get("agent_name") == "agent-07-marketing"]
        assert draft, "draft provenance missing"
        p = draft[0]
        assert p["model_id"] and p["model_version"] and p["prompt_hash"] == areq["payload"]["prompt_hash"]
        assert {"ref": "draft_content", "hash": areq["payload"]["content_hash"]} in p["inputs_used"]


def test_injected_listing_text_never_reaches_outbound_copy(ran):
    flip = next(d for k, d in ran.store.all_documents() if k == "item" and d["type"] == "flip")
    assert "injection_suspected" in flip["normalized"]["flags"]
    assert ran.store.receipts(type="INJECTION_SUSPECTED", item_id=flip["item_id"])
    for areq in ran.store.action_requests(item_id=flip["item_id"]):
        assert areq["tier"] == 0 and areq["untrusted_inputs_present"] is True
        blob = str(areq["payload"]).lower()
        for phrase in ("ignore all previous instructions", "wire a $500", "$500 deposit", "soft floor"):
            assert phrase not in blob, f"untrusted listing text leaked into a draft: {phrase!r}"


def test_drafts_are_deterministic():
    item = {"item_id": "itm_x", "subcategory": "thing", "category": "trailer",
            "normalized": {"title": "t", "location": {"city": "Conway", "state": "AR"}}}
    a = drafts.resale_listing(item, price=100, work_done="w", unknowns="u", platform="p")
    b = drafts.resale_listing(item, price=100, work_done="w", unknowns="u", platform="p")
    assert a == b and a["content_hash"] == b["content_hash"]
