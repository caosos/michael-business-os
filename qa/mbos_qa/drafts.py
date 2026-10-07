"""Draft generators for outbound content. Owner: Agent 07 (marketing drafts → ActionRequests, ADR-0006 §3).

Deterministic templates — no LLM is called in wave one. Every draft carries the G4 provenance triple:
content hash, prompt/template version (+ hash), and model id (explicitly "none" here). Seller- or
customer-supplied text is never copied into a draft; only normalized, typed fields are used, so a
prompt-injection string in a listing cannot reach outbound copy.
"""
from __future__ import annotations

from .core import sha256_ref

TOOL_NAME = "mbos_qa.drafts"
TOOL_VERSION = "0.1.0"
MODEL_ID = "none:deterministic-template"

TEMPLATES = {
    "seller_inquiry_v1": {
        "version": "1",
        "subject": "Question about your {title_short}",
        "body": (
            "Hi,\n\nI saw your listing for the {title_short} in {city}. Is it still available?\n"
            "{questions}\n"
            "If everything checks out I could pay ${offer:,.0f} cash and pick it up myself.\n"
            "This is a question, not a binding offer.\n\nThanks,\nMichael"
        ),
    },
    "resale_listing_v1": {
        "version": "1",
        "title": "{title_short} — {condition_summary}",
        "body": (
            "{title_short}. {condition_summary}.\n\n"
            "Work done: {work_done}.\n"
            "Known unknowns disclosed: {unknowns}.\n\n"
            "Located near {city}, {state}. Cash or verified payment at pickup. No holds without deposit."
        ),
    },
    "service_quote_v1": {
        "version": "1",
        "subject": "Your {service_name} estimate",
        "body": (
            "Hi,\n\nThanks for reaching out about {service_name} in {city}.\n"
            "Based on what you described, my estimate is ${price:,.0f} ({scope}).\n"
            "Final price is confirmed after I see the area in person; no work starts without your OK.\n\n"
            "Thanks,\nMichael"
        ),
    },
}


def template_hash(template_id: str) -> str:
    return sha256_ref(TEMPLATES[template_id])


def _render(template_id: str, fields: dict, **params) -> dict:
    t = TEMPLATES[template_id]
    return {k: (t[k].format(**params) if isinstance(t[k], str) else t[k]) for k in fields}


def build_payload(*, template_id: str, channel: str, content: dict, policy_checks: list[str] | None = None) -> dict:
    return {
        "channel": channel,
        "template_id": template_id,
        "template_version": TEMPLATES[template_id]["version"],
        "prompt_hash": template_hash(template_id),
        "model_id": MODEL_ID,
        "ai_generated": False,
        "content": content,
        "content_hash": sha256_ref(content),
        "policy_checks": policy_checks or [],
        "dry_run": True,
    }


def draft_provenance(pid: str, created_at: str, *, template_id: str, item: dict, content_hash: str) -> dict:
    return {
        "provenance_id": pid, "created_at": created_at, "actor_type": "agent", "agent_name": "agent-07-marketing",
        "basis": "RECOMMENDATION", "tool_name": TOOL_NAME, "tool_version": TOOL_VERSION,
        "model_id": MODEL_ID, "model_version": f"{template_id}@{TEMPLATES[template_id]['version']}",
        "prompt_hash": template_hash(template_id),
        "inputs_used": [{"ref": item["item_id"], "hash": sha256_ref(item["normalized"])},
                        {"ref": "draft_content", "hash": content_hash}],
    }


def seller_inquiry(item: dict, *, offer: float, questions: list[str]) -> dict:
    n = item["normalized"]
    content = _render("seller_inquiry_v1", ("subject", "body"),
                      title_short=item.get("subcategory") or n["title"], city=n["location"]["city"],
                      offer=offer, questions="\n".join(f"- {q}" for q in questions))
    return build_payload(template_id="seller_inquiry_v1", channel="email (platform relay)", content=content)


def resale_listing(item: dict, *, price: float, work_done: str, unknowns: str, platform: str) -> dict:
    n = item["normalized"]
    title_short = item.get("subcategory") or n["title"]
    condition_summary = "refurbished, road-ready" if item["category"] == "trailer" else "refurbished"
    content = _render("resale_listing_v1", ("title", "body"), title_short=title_short,
                      condition_summary=condition_summary, work_done=work_done, unknowns=unknowns,
                      city=n["location"]["city"], state=n["location"]["state"])
    content["price"] = price
    return build_payload(template_id="resale_listing_v1", channel=f"{platform} (manual-assist; no API)",
                         content=content)


def service_quote(item: dict, *, price: float, scope: str) -> dict:
    n = item["normalized"]
    content = _render("service_quote_v1", ("subject", "body"), service_name=item.get("subcategory") or n["title"],
                      city=n["location"]["city"], price=price, scope=scope)
    return build_payload(template_id="service_quote_v1", channel="email (reply to inbound form)", content=content)
