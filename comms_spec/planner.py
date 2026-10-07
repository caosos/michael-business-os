"""F-05: CommsActionPlanner, an `mbos.interfaces.ActionPlanner` that drafts from the template registry.

For a YES item it returns ONE proposed action: the first contact. That is a non-binding seller inquiry
(flip) or a customer intake acknowledgement (service). Offers and quotes are binding. They come later,
after Q&A, as their own requests (tier 0 + step-up; see `comms_spec.action_constraints`), and never
as a first contact.

Each proposed action is a valid `Item.recommendation.proposed_actions[]` entry (capability, summary,
reversibility, estimated_cost) plus a `comms` block. A-13 (Agent 01) copies that block into the
ActionRequest payload, so the payload Michael approves carries `template_id`, `template_hash`
(MBOS-CJSON-1) and the exact rendered draft. The dry-run effector (F-06) sends only that frozen draft.
Nothing here sends.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

import comms_spec as cs

# Single-timezone US states only. Multi-zone states → None → the send window denies (fail closed).
STATE_TZ = {
    "AR": "America/Chicago", "LA": "America/Chicago", "MS": "America/Chicago", "MO": "America/Chicago",
    "OK": "America/Chicago", "IA": "America/Chicago", "MN": "America/Chicago", "WI": "America/Chicago",
    "IL": "America/Chicago", "AL": "America/Chicago", "AZ": "America/Phoenix", "CO": "America/Denver",
    "UT": "America/Denver", "NM": "America/Denver", "MT": "America/Denver", "WY": "America/Denver",
    "CA": "America/Los_Angeles", "WA": "America/Los_Angeles", "NV": "America/Los_Angeles",
    "GA": "America/New_York", "OH": "America/New_York", "NC": "America/New_York", "SC": "America/New_York",
    "VA": "America/New_York", "PA": "America/New_York", "NY": "America/New_York",
}
CHANNEL_BY_CONTACT = {"relay_email": "email", "email": "email", "phone": "sms"}
MANUAL_ASSIST = {"platform", "in_app", "gov_poc"}  # drafted as email text; Michael delivers it by hand
SERVICE_NAMES = {
    "mobile_repair": "phone/tablet repair", "equipment_repair": "equipment repair", "drywall_repair": "drywall repair",
    "assembly": "assembly", "handyman": "handyman work", "smart_home_install": "smart-home install",
    "technical_service": "tech help", "mechanical_service": "mechanical repair", "other_service": "your project",
}
ZERO = {"amount": 0, "currency": "USD"}
LANE = "agent-06-communications"  # the drafting lane: lane E stamps `proposed_by` from it (F-15 / E-15 / 07 F-41)


def sanitize(text: Any, limit: int = 80) -> str:
    """Listing text is UNTRUSTED (it can carry prompt or template injection). Before it goes into an
    outbound draft: drop control/format characters, template braces, angle brackets and URLs; collapse
    whitespace; cap the length."""
    s = re.sub(r"\s", " ", str(text or ""))  # whitespace controls (\n, \t) become spaces first
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")
    s = re.sub(r"https?://\S+|www\.\S+", "", s)
    s = re.sub(r"[{}<>]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return (s[: limit - 1] + "…") if len(s) > limit else s


def _route(item: dict[str, Any]) -> Optional[tuple[str, str, str]]:
    """(channel, delivery, contact_method) for the item's counterparty, or None if there is no route."""
    method = (item["normalized"].get("counterparty") or {}).get("contact_method", "none")
    if method in CHANNEL_BY_CONTACT:
        return CHANNEL_BY_CONTACT[method], "effector", method
    if method in MANUAL_ASSIST:
        return "email", "manual_assist", method
    return None


def _money(x: Any, what: str) -> str:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not (0 < x < 1_000_000):
        raise ValueError(f"{what} must be a positive dollar amount, got {x!r}")
    return f"{x:,.0f}"


def _build(planner: str, item: dict[str, Any], route: tuple[str, str, str], template_id: str, channel: str,
           variables: dict[str, Any], summary: str, *, first_message: bool, question_ids: list[str],
           untrusted: list[str]) -> dict[str, Any]:
    _, delivery, method = route
    draft = cs.render(template_id, channel, variables)
    constraints = cs.action_constraints(draft)
    policy = cs.load("comms_policy")
    loc = item["normalized"].get("location") or {}
    cp = item["normalized"].get("counterparty") or {}
    # NB: the payload block must not contain the keys lane E's PDP reserves for binding offers under comms.* / publish.*
    # (policy `recommendation_actions.binding_payload_keys`: offer, offer_amount, counter, binding, ...), at any depth.
    # Hence `is_binding`, not `binding`. A test pins this against the real policy file.
    comms = {
        "template_id": draft["template_id"], "template_version": draft["template_version"],
        "template_hash": draft["template_hash"], "template_approval": draft["template_approval"],
        "channel": channel, "delivery": delivery, "subject": draft["subject"], "body": draft["body"],
        "variables": variables, "question_ids": question_ids,
        "first_message": first_message, "is_binding": draft["binding"], "commercial": draft["commercial"],
        "recipient": {"ref": (item.get("sources") or [{}])[0].get("url"), "contact_method": method,
                      "role": cp.get("role"), "tz": STATE_TZ.get((loc.get("state") or "").upper())},
        "constraints": {
            **constraints,
            "send_window": {**policy["send_window"]["effective"],
                            "no_outbound_days": policy["send_window"]["no_outbound_days"], "basis": "recipient local time"},
            "rate_limit": policy["rate_limits"]["per_contact"][channel],
            "consent_prerequisites": policy["consent"]["record_on_every_send"],
            "dnc_required": channel in policy["dnc"]["applies_to"],
            "disclosure_required": first_message,
        },
        "untrusted_fields": untrusted,
        "planner": planner,
    }
    # Binding drafts are proposed under offer.<channel>.send, so the spine classifies them as category
    # `offer` (effect commit): tier 0, step-up, and 05's offer policy. Never as plain comms.
    prefix = "offer" if draft["binding"] else "comms"
    return {
        "capability": f"{prefix}.{channel}.send",
        "summary": summary + (" — MANUAL ASSIST: Michael pastes it into the platform" if delivery == "manual_assist" else ""),
        "reversibility": constraints["reversibility"],
        "estimated_cost": ZERO,
        "lane": LANE,
        "comms": comms,
    }


class CommsActionPlanner:
    name = "comms-action-planner"
    version = "0.2.0"

    @property
    def _id(self) -> str:
        return f"{self.name}@{self.version}"

    def plan(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        """ActionPlanner protocol: the FIRST contact for a YES item. It is never binding."""
        route = _route(item)
        if route is None:
            return []  # no contact route → the spine parks the item in RESEARCHING (nothing is invented)
        channel = route[0]
        lane, category = item["type"], item["category"]
        qs = cs.questions(lane, category)
        if lane == "flip":
            template_id = "seller_first_inquiry"
            variables = {"listing_title": sanitize(item["normalized"]["title"]),
                         "question_1": qs[0]["q"], "question_2": qs[1]["q"]}
            summary = f"Ask the seller about the {variables['listing_title']} (first contact, no offer)"
        else:
            template_id = "customer_intake_ack"
            channel = "email" if channel == "sms" else channel  # registry has no intake SMS yet
            variables = {"service_name": SERVICE_NAMES.get(category, "your project"),
                         "question_1": qs[0]["q"], "question_2": qs[1]["q"]}
            summary = f"Acknowledge the {variables['service_name']} request and ask two scoping questions"
        if channel == "sms":  # SMS first inquiry takes one question
            variables.pop("question_2", None)
        return [_build(self._id, item, route, template_id, channel, variables, summary, first_message=True,
                       question_ids=[q["id"] for q in qs[:2]],
                       untrusted=["listing_title"] if lane == "flip" else [])]

    # ---- F-08: later actions on the same item. Each is its OWN ActionRequest; nothing auto-sends.
    def plan_followup(self, item: dict[str, Any], asked: list[str] = ()) -> list[dict[str, Any]]:
        """Next Q&A step (non-binding): the next two unasked questions (email), or a photo request (SMS / service)."""
        route = _route(item)
        if route is None:
            return []
        channel = route[0]
        lane, category = item["type"], item["category"]
        remaining = [q for q in cs.questions(lane, category) if q["id"] not in set(asked)]
        if not remaining:
            return []
        if lane == "flip" and channel == "email" and len(remaining) >= 2:
            variables = {"listing_title": sanitize(item["normalized"]["title"]),
                         "question_1": remaining[0]["q"], "question_2": remaining[1]["q"]}
            return [_build(self._id, item, route, "seller_followup_questions", "email", variables,
                           f"Follow-up questions about the {variables['listing_title']}", first_message=False,
                           question_ids=[q["id"] for q in remaining[:2]], untrusted=["listing_title"])]
        if lane == "flip":
            if channel != "sms":
                return []  # one question left on email: Michael asks it himself (no single-question template yet)
            return [_build(self._id, item, route, "seller_photo_request", "sms", {"photo_subject": "the problem areas"},
                           "Ask the seller for photos of the problem areas", first_message=False,
                           question_ids=["photos"], untrusted=[])]
        variables = {"service_name": SERVICE_NAMES.get(category, "your project"), "photo_subject": "the area"}
        return [_build(self._id, item, route, "customer_photo_request", "email", variables,
                       f"Ask the customer for photos to firm up the {variables['service_name']} quote",
                       first_message=False, question_ids=["photos"], untrusted=[])]

    def plan_offer(self, item: dict[str, Any], amount: float, pickup_window: str, offer_expires: str) -> list[dict[str, Any]]:
        """BINDING cash offer on a flip. Category offer, tier 0, irreversible, step-up. Never above the ask."""
        if item["type"] != "flip":
            raise ValueError("offers are for flips; services get quotes")
        route = _route(item)
        if route is None:
            return []
        ask = (item["normalized"].get("price") or {}).get("amount")
        offer = _money(amount, "offer")
        if isinstance(ask, (int, float)) and amount > ask:
            raise ValueError(f"offer ${offer} is above the asking price ${ask:,.0f}; refusing to draft it")
        variables = {"listing_title": sanitize(item["normalized"]["title"]), "offer_amount": offer,
                     "pickup_window": sanitize(pickup_window, 40), "offer_expires": sanitize(offer_expires, 40)}
        return [_build(self._id, item, route, "seller_offer", "email", variables,
                       f"BINDING OFFER: ${offer} cash for the {variables['listing_title']}", first_message=False,
                       question_ids=[], untrusted=["listing_title"])]

    def plan_quote(self, item: dict[str, Any], amount: float, scope_summary: str, deposit_pct: int,
                   quote_expires: str) -> list[dict[str, Any]]:
        """BINDING price quote for a service. Category offer, tier 0, irreversible, step-up."""
        if item["type"] != "service":
            raise ValueError("quotes are for services; flips get offers")
        route = _route(item)
        if route is None:
            return []
        if not (isinstance(deposit_pct, int) and 0 <= deposit_pct <= 50):
            raise ValueError("deposit_pct must be an integer 0-50")
        quote = _money(amount, "quote")
        variables = {"service_name": SERVICE_NAMES.get(item["category"], "your project"),
                     "scope_summary": sanitize(scope_summary, 120), "quote_amount": quote,
                     "deposit_pct": str(deposit_pct), "quote_expires": sanitize(quote_expires, 40)}
        return [_build(self._id, item, route, "customer_quote", "email", variables,
                       f"BINDING QUOTE: ${quote} for {variables['scope_summary']}", first_message=False,
                       question_ids=[], untrusted=[])]


def payload_extension(proposed_action: dict[str, Any]) -> Optional[dict[str, Any]]:
    """What A-13 merges into the ActionRequest payload: {'comms': <draft block>}."""
    return {"comms": proposed_action["comms"]} if "comms" in proposed_action else None
