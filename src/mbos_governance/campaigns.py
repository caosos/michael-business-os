"""E-17: campaign autonomy -> governance (ADR-0013 §9). Policy is DATA (policy.v1.json -> campaigns); this is a pure,
non-LLM, fail-closed decision function.

  WATCH_ONLY / RECOMMEND  -> no action may be requested (decision "no_action")
  ASSISTED_DEAL           -> may DRAFT offer.* / comms.* requests only; tier 0 + step-up + Michael's YES (the existing path)
  BOUNDED_AUTOPILOT       -> DENIED: AUTOPILOT_NOT_AUTHORIZED, even with valid limits (until a later explicit Michael
                             decision AND a schema change; the policy schema pins this)
  anything else / invalid -> DENIED, fail closed

A campaign authorises nothing by itself. Campaign-sourced ActionRequests are additionally TAINTED by the gateway
(untrusted_inputs_present) so tier 0 and step-up are forced, and the normal guard (G1 approval ... G8) still applies:
there is no path from a campaign to an executed request without an approved, unexpired YES on the exact payload hash.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from .ids import parse_ts
from .policy import Policy


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(resources.files("mbos_governance.schemas").joinpath("campaign.schema.json").read_text("utf-8")))


@dataclass(frozen=True)
class CampaignDecision:
    level: str | None
    decision: str            # no_action | require_approval | deny
    may_request_action: bool
    tier: int | None
    step_up: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "decision": self.decision, "may_request_action": self.may_request_action,
                "tier": self.tier, "step_up": self.step_up, "reasons": list(self.reasons)}


def _deny(level: str | None, *reasons: str) -> CampaignDecision:
    return CampaignDecision(level, "deny", False, None, False, list(reasons))


def decide_campaign(campaign: Any, policy: Policy, *, capability: str | None = None, cost_usd: float | None = None,
                    now: datetime | None = None) -> CampaignDecision:
    """Decide what a campaign may do. `capability`/`cost_usd` describe a specific request it wants to draft (optional)."""
    now = now or datetime.now(timezone.utc)
    cfg = policy.data["campaigns"]
    level = ((campaign or {}).get("autonomy") or {}).get("level") if isinstance(campaign, dict) else None
    if level not in cfg["levels"]:
        return _deny(level if isinstance(level, str) else None, cfg["unknown_level"]["reason"], f"level={level!r}")
    errs = [f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:100]}" for e in _validator().iter_errors(campaign)]
    if errs:
        return _deny(level, "CAMPAIGN_INVALID", errs[0])
    spec = cfg["levels"][level]
    if campaign["status"] != "ACTIVE":
        return _deny(level, f"CAMPAIGN_NOT_ACTIVE:{campaign['status']}")
    exp = (campaign.get("stop_conditions") or {}).get("expires_at")
    try:
        if exp and parse_ts(exp) <= now:
            return _deny(level, "CAMPAIGN_EXPIRED")
    except ValueError:
        return _deny(level, "CAMPAIGN_INVALID", "stop_conditions.expires_at")
    if not spec["may_request_action"]:
        if spec["decision"] == "deny":                     # BOUNDED_AUTOPILOT: valid limits change nothing
            return _deny(level, spec["reason"])
        return CampaignDecision(level, "no_action", False, None, False, [spec["reason"]])
    # ASSISTED_DEAL: draft only, through the existing step-up path
    if capability is not None and not capability.startswith(tuple(spec["allowed_capability_prefixes"])):
        return _deny(level, f"CAMPAIGN_CAPABILITY_NOT_ALLOWED:{capability}")
    if cfg["enforce_max_price"] and cost_usd is not None and cost_usd > campaign["criteria"]["max_price_usd"]:
        return _deny(level, f"OFFER_EXCEEDS_CAMPAIGN_MAX:{cost_usd}>{campaign['criteria']['max_price_usd']}")
    return CampaignDecision(level, "require_approval", True, spec["tier"], spec["step_up"], [spec["reason"]])
