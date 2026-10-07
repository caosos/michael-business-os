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


class CommsActionPlanner:
    name = "comms-action-planner"
    version = "0.1.0"

    def plan(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        cp = item["normalized"].get("counterparty") or {}
        method = cp.get("contact_method", "none")
        if method in CHANNEL_BY_CONTACT:
            channel, delivery = CHANNEL_BY_CONTACT[method], "effector"
        elif method in MANUAL_ASSIST:
            channel, delivery = "email", "manual_assist"
        else:
            return []  # no contact route → the spine parks the item in RESEARCHING (nothing is invented)
        lane, category = item["type"], item["category"]
        qs = cs.questions(lane, category)
        loc = item["normalized"].get("location") or {}
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
        draft = cs.render(template_id, channel, variables)
        constraints = cs.action_constraints(draft)
        policy = cs.load("comms_policy")
        comms = {
            "template_id": draft["template_id"], "template_version": draft["template_version"],
            "template_hash": draft["template_hash"], "template_approval": draft["template_approval"],
            "channel": channel, "delivery": delivery, "subject": draft["subject"], "body": draft["body"],
            "variables": variables, "question_ids": [q["id"] for q in qs[:2]],
            "first_message": True, "binding": draft["binding"], "commercial": draft["commercial"],
            "recipient": {"ref": (item.get("sources") or [{}])[0].get("url"), "contact_method": method,
                          "role": cp.get("role"), "tz": STATE_TZ.get((loc.get("state") or "").upper())},
            "constraints": {
                **constraints,
                "send_window": {**policy["send_window"]["effective"],
                                "no_outbound_days": policy["send_window"]["no_outbound_days"], "basis": "recipient local time"},
                "rate_limit": policy["rate_limits"]["per_contact"][channel],
                "consent_prerequisites": policy["consent"]["record_on_every_send"],
                "dnc_required": channel in policy["dnc"]["applies_to"],
                "disclosure_required": True,
            },
            "untrusted_fields": ["listing_title"] if lane == "flip" else [],
            "planner": f"{self.name}@{self.version}",
        }
        return [{
            "capability": f"comms.{channel}.send",
            "summary": summary + (" — MANUAL ASSIST: Michael pastes it into the platform" if delivery == "manual_assist" else ""),
            "reversibility": constraints["reversibility"],
            "estimated_cost": ZERO,
            "comms": comms,
        }]


def payload_extension(proposed_action: dict[str, Any]) -> Optional[dict[str, Any]]:
    """What A-13 merges into the ActionRequest payload: {'comms': <draft block>}."""
    return {"comms": proposed_action["comms"]} if "comms" in proposed_action else None
