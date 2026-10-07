"""G-05: determinism. Same facts → same card_hash, independent of the ORDER the loader happens to return rows in,
of the process, and of generation time; and the hash must mean something (a tampered card must not pass)."""
import copy
import json
import os
import random
import subprocess
import sys
import textwrap

from .conftest import QA, areq_doc, base_item, receipt, world


def _rich(mc, profile, shuffle_seed=None):
    item, rs, ar = world(state="AWAITING_APPROVAL", flow=("DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED",
                                                         "RECOMMENDED", "AWAITING_APPROVAL"))
    iid = item["item_id"]
    old = areq_doc(iid, status="rejected", n=11)
    mid = areq_doc(iid, cap="comms.sms.send", status="held", n=12)
    new = areq_doc(iid, status="pending_approval", n=13)
    old["created_at"], mid["created_at"], new["created_at"] = "2026-10-06T10:00:00Z", "2026-10-06T11:00:00Z", "2026-10-06T12:00:00Z"
    ar = [old, mid, new]
    rs = rs + [receipt(40 + i, t, iid, areq=new["action_request_id"], intent=f"i{i}") for i, t in
               enumerate(["ACTION_PROPOSED", "POLICY_DECIDED", "APPROVAL_REQUESTED"])]
    if shuffle_seed is not None:
        rnd = random.Random(shuffle_seed)
        rnd.shuffle(rs)
        rnd.shuffle(ar)
    return mc.build_card(item, rs, ar, {"why": ["a", "b"], "seasonality": {"peak_months": [3, 4]}}, profile=profile)


def test_card_hash_is_independent_of_receipt_and_request_order(mc, profile):
    ref = _rich(mc, profile)
    bad = [s for s in range(60) if _rich(mc, profile, s)["card_hash"] != ref["card_hash"]]
    assert not bad, f"card_hash changed for {len(bad)}/60 input orderings (first seeds {bad[:5]}); " \
                    f"recommendation: {_rich(mc, profile, bad[0])['recommendation']['action_request_id'][-6:] if bad else ''}"


def test_text_view_is_independent_of_input_order(mc, profile):
    ref = mc.render_text(_rich(mc, profile))
    assert all(mc.render_text(_rich(mc, profile, s)) == ref for s in range(20))


def test_card_hash_ignores_generation_time_but_nothing_else(mc, profile):
    from datetime import datetime, timezone

    item, rs, ar = world()
    a = mc.build_card(item, rs, ar, None, profile=profile, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    b = mc.build_card(item, rs, ar, None, profile=profile, now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert a["generated_at"] != b["generated_at"] and a["card_hash"] == b["card_hash"]
    c = mc.build_card({**item, "normalized": {**item["normalized"], "title": item["normalized"]["title"] + "!"}}, rs, ar,
                      None, profile=profile)
    assert c["card_hash"] != a["card_hash"], "a changed title did not change the hash"


def test_card_hash_is_stable_across_processes_and_hash_seeds(mc, profile):
    code = textwrap.dedent(f"""
        import sys; sys.path.insert(0, {str(QA)!r})
        from tests.card.conftest import world
        import mbos.card as mc
        print(mc.build_card(*world(), None, profile=mc.load_profile())['card_hash'])
    """)
    hashes = set()
    for seed in ("0", "1", "12345"):
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=QA,
                             env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(QA)})
        assert out.returncode == 0, out.stderr[-500:]
        hashes.add(out.stdout.strip().splitlines()[-1])
    assert len(hashes) == 1, hashes


def test_key_order_and_float_representation_do_not_change_the_hash(mc, profile):
    item, rs, ar = world()
    a = mc.build_card(item, rs, ar, {"economics": {"opening_offer": {"value": 850.0, "basis": "INFERENCE"}}}, profile=profile)
    b = mc.build_card(json.loads(json.dumps(item, sort_keys=True)), rs, ar,
                      {"economics": {"opening_offer": {"basis": "INFERENCE", "value": 850}}}, profile=profile)
    assert a["card_hash"] == b["card_hash"]


def test_card_hash_matches_an_independent_recomputation(mc, profile):
    from mbos_qa.core import mbos_canonical

    card = _rich(mc, profile)
    body = {k: v for k, v in card.items() if k not in ("generated_at", "card_hash")}
    assert card["card_hash"] == mbos_canonical.sha256_of(body), "card_hash is not MBOS-CJSON-1 over the card body"


def test_a_tampered_card_does_not_pass_validation(mc, profile):
    """card_hash is only meaningful if validate_card checks it. Flip the recommendation and keep the old hash."""
    card = _rich(mc, profile)
    forged = copy.deepcopy(card)
    forged["recommendation"]["action"] = "BUY"
    forged["recommendation"]["why"] = "pre-approved"
    assert mc.validate_card(forged), "a card whose body no longer matches its card_hash passed validation"


def test_building_a_card_does_not_mutate_its_inputs(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL")
    enr = {"why": ["x"], "value_add": {"model_specific_risks": [{"risk": "r", "basis": "FACT", "source": "s"}]}}
    snap = copy.deepcopy((item, rs, ar, enr))
    mc.build_card(item, rs, ar, enr, profile=profile)
    assert (item, rs, ar, enr) == snap, "build_card mutated its inputs"
    assert base_item()  # keep helper imported
