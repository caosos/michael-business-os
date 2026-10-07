"""G-05: activity trail (R17: no invisible autonomous actions) and status timeline (R16: a stage appears only with an event).
Pure tests on synthetic-but-valid histories; the same properties over real flows are in test_card_backends.py."""
import random


from .conftest import areq_doc, base_item, independent_schema_errors, pid, receipt, world


def _flow(mc, profile, *, state, flow, extra=(), areq_status="pending_approval"):
    item, rs, ar = world(state=state, flow=flow, areq_status=areq_status)
    n = len(rs)
    rs = rs + [r(n + 1 + i) if callable(r) else r for i, r in enumerate(extra)]
    return item, rs, ar, mc.build_card(item, rs, ar, None, profile=profile)


# ---------------------------------------------------------------- activity trail
def test_trail_is_the_items_receipts_one_to_one_in_seq_order(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL")
    card = mc.build_card(item, random.Random(3).sample(rs, len(rs)), ar, None, profile=profile)
    assert [t["receipt_id"] for t in card["activity_trail"]] == [r["receipt_id"] for r in sorted(rs, key=lambda x: x["seq"])]


def test_every_trail_row_has_its_input_provenance(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL")
    card = mc.build_card(item, rs, ar, None, profile=profile)
    assert card["activity_trail"] and all(t["inputs"] for t in card["activity_trail"])
    by_id = {r["receipt_id"]: r for r in rs}
    for t in card["activity_trail"]:
        assert t["inputs"] == by_id[t["receipt_id"]]["provenance_ids"]
        assert t["agent"] == by_id[t["receipt_id"]]["actor"]["id"] and t["why"] == by_id[t["receipt_id"]]["intent"]


def test_a_receipt_without_provenance_never_becomes_a_trail_row_silently(mc, profile):
    """'No receipt without provenance.' If one slips in anyway, the card must refuse or flag it, not show a row whose
    input provenance is empty as if it were fine."""
    item, rs, ar = world(state="AWAITING_APPROVAL")
    rs.append(receipt(99, "ITEM_STATE_CHANGED", item["item_id"], prov=[], after={"state": "HELD"}))
    try:
        card = mc.build_card(item, rs, ar, None, profile=profile)
    except Exception:
        return  # refusing is acceptable
    ok = mc.validate_card(card) != [] or independent_schema_errors(card) != [] or \
        not any(t["inputs"] == [] for t in card["activity_trail"])
    assert ok, "a trail row with NO input provenance was accepted as a valid card"


def test_receipts_of_other_items_do_not_leak_into_the_trail(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL")
    other = base_item(item_id="itm_" + pid(5)[5:])
    rs.append(receipt(50, "ITEM_STATE_CHANGED", other["item_id"], after={"state": "DISCOVERED"}, intent="OTHER ITEM"))
    card = mc.build_card(item, rs, ar, None, profile=profile)
    assert not any("OTHER ITEM" in t["why"] for t in card["activity_trail"]), "another item's receipt appeared in this trail"


def test_receipts_tied_to_the_items_requests_but_lacking_item_id_still_appear(mc, profile):
    """Autonomous actions on the item's requests must not be invisible just because a lane omitted item_id."""
    item, rs, ar = world(state="AWAITING_APPROVAL")
    r = receipt(60, "ACTION_EXECUTED", item["item_id"], areq=ar[0]["action_request_id"], intent="gateway executed")
    r.pop("item_id")
    card = mc.build_card(item, rs + [r], ar, None, profile=profile)
    assert any(t["receipt_id"] == r["receipt_id"] for t in card["activity_trail"]), "request-scoped receipt is invisible"


def test_next_action_is_stated_exactly_once_on_the_last_row(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL")
    t = mc.build_card(item, rs, ar, None, profile=profile)["activity_trail"]
    assert all(x["next_action"] == "(done)" for x in t[:-1]) and t[-1]["next_action"] != "(done)"


# ---------------------------------------------------------------- timeline
FORBIDDEN_WITHOUT_EVENT = ("NEGOTIATING", "QUALIFIED")


def test_negotiating_and_qualified_never_appear_without_an_event(mc, profile):
    """No event source exists for them in wave one. Try hard to make the card invent them."""
    rnd = random.Random(7)
    words = ["negotiating", "qualified", "NEGOTIATING", "QUALIFIED", "counter-offer", "seller agreed", "deal done"]
    kinds = ["negotiating", "qualified", "message_replied", "service_won", "flip_acquired", "lead_attributed", None]
    for i in range(200):
        item, rs, ar = world(state=rnd.choice(["RECOMMENDED", "AWAITING_APPROVAL", "HELD", "ACTED", "OUTCOME_RECORDED"]))
        for j in range(rnd.randrange(1, 6)):
            t = rnd.choice(["OUTCOME_RECORDED", "ITEM_STATE_CHANGED", "APPROVAL_DECIDED", "ACTION_EXECUTED", "SCORE_RECORDED"])
            k = rnd.choice(kinds)
            rs.append(receipt(100 + j, t, item["item_id"], areq=ar[0]["action_request_id"], intent=rnd.choice(words),
                              after={"state": rnd.choice(words), "decision": rnd.choice(["YES", "negotiating", None]),
                                     **({"kind": k} if k else {})}))
        card = mc.build_card(item, rs, ar, {"why": [rnd.choice(words)]}, profile=profile)
        stages = {s["stage"] for s in card["status"]["timeline"]} | {card["status"]["current"]}
        assert not stages & set(FORBIDDEN_WITHOUT_EVENT), (i, stages)


def test_every_timeline_stage_is_backed_by_a_receipt_with_the_right_timestamp(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL", flow=("DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED",
                                                         "RECOMMENDED", "AWAITING_APPROVAL"))
    card = mc.build_card(item, rs, ar, None, profile=profile)
    by_id = {r["receipt_id"]: r for r in rs}
    assert card["status"]["timeline"]
    for s in card["status"]["timeline"]:
        assert s["receipt_id"] in by_id and by_id[s["receipt_id"]]["ts"] == s["at"], s


def test_an_attribution_outcome_does_not_close_a_live_lead(mc, profile):
    """Lead attribution is captured at intake (G2). It is not the end of the lead."""
    item, rs, ar = world(state="AWAITING_APPROVAL", flow=("DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED",
                                                         "RECOMMENDED", "AWAITING_APPROVAL"))
    rs.append(receipt(90, "OUTCOME_RECORDED", item["item_id"], intent="lead attribution captured at intake",
                      entity_type="outcome"))
    card = mc.build_card(item, rs, ar, None, profile=profile)
    stages = [s["stage"] for s in card["status"]["timeline"]]
    assert "CLOSED" not in stages, f"a live lead shows as CLOSED after attribution: {stages}"
    assert card["recommendation"]["action"] != "PASS" or card["status"]["current"] != "CLOSED"


def _dry_run_card(mc, profile):
    a = areq_doc(base_item()["item_id"], status="executed")
    item, rs, _ = world(state="ACTED", flow=("DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED",
                                             "AWAITING_APPROVAL", "APPROVED", "ACTING", "ACTED"))
    rs.append(receipt(70, "ACTION_EXECUTED", item["item_id"], areq=a["action_request_id"], capability="comms.email.send",
                      intent="DRY-RUN comms.email.send executed", effector_response={"status": "simulated", "dry_run": True,
                                                                                     "provider": "dry-run"}))
    return mc.build_card(item, rs, [a], None, profile=profile)


def test_a_dry_run_execution_is_labelled_and_never_waits_for_a_seller(mc, profile):
    """Wave one is DRY-RUN: nothing leaves the system. The timeline row must say so, the recommendation must not wait
    for a reply, and must say nothing was sent (F-31 fix)."""
    card = _dry_run_card(mc, profile)
    sent = [s for s in card["status"]["timeline"] if s["stage"] == "CONTACT SENT"]
    assert sent and all(s.get("dry_run") is True for s in sent), card["status"]["timeline"]
    assert card["recommendation"]["waiting"] is False
    why = card["recommendation"]["why"].lower()
    assert "nothing has been sent" in why or "not sent" in why, why
    text = mc.render_text(card)
    assert any("CONTACT SENT" in ln and "DRY-RUN" in ln for ln in text.split("\n")), "the stage row does not say DRY-RUN"
    assert "WAIT FOR RESPONSE" not in text and "Already contacted" not in text


def test_the_headline_status_never_says_contact_sent_without_saying_dry_run(mc, profile):
    """Michael reads the 'SYSTEM STATUS' headline and '[now: ...]' first. The DRY-RUN label is on the detail row only;
    the headline chain and `status.current` still read 'Contact Sent'."""
    card = _dry_run_card(mc, profile)
    text = mc.render_text(card)
    head = next(ln for ln in text.split("\n") if ln.startswith("SYSTEM STATUS"))
    assert "Contact Sent" not in head or "dry" in head.lower(), f"headline reads as a real send: {head!r}"
    assert card["status"]["current"] != "CONTACT SENT" or "dry" in head.lower()


def test_michaels_yes_on_a_contact_request_appears_as_contact_approved(mc, profile):
    """The event source exists (APPROVAL_DECIDED + the request), so the stage must appear."""
    a = areq_doc(base_item()["item_id"], status="approved")
    item, rs, _ = world(state="APPROVED", flow=("DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED",
                                                "AWAITING_APPROVAL", "APPROVED"))
    rs.append(receipt(71, "APPROVAL_DECIDED", item["item_id"], areq=a["action_request_id"], intent="Michael decided YES",
                      approval_id="appr_" + pid(2)[5:], capability="comms.email.send"))
    card = mc.build_card(item, rs, [a], None, profile=profile)
    assert "CONTACT APPROVED" in [s["stage"] for s in card["status"]["timeline"]], \
        "Michael's YES is on the ledger but the timeline does not show it"


def test_a_seller_reply_is_not_a_closed_deal(mc, profile):
    a = areq_doc(base_item()["item_id"], status="executed")
    item, rs, _ = world(state="OUTCOME_RECORDED", flow=("DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED",
                                                        "AWAITING_APPROVAL", "APPROVED", "ACTING", "ACTED", "OUTCOME_RECORDED"))
    rs.append(receipt(72, "OUTCOME_RECORDED", item["item_id"], intent="outcome message_replied recorded",
                      entity_type="outcome", entity_id="outc_" + pid(3)[5:]))
    card = mc.build_card(item, rs, [a], None, profile=profile)
    stages = [s["stage"] for s in card["status"]["timeline"]]
    assert "SELLER RESPONDED" in stages, f"a recorded seller reply is not on the timeline: {stages}"
