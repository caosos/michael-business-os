"""Pydantic v2 models aligned with the FROZEN v1.0.0 contracts (ADR-0004).

Alignment rules:
- Field names and enums mirror `docs/research/contracts/*.schema.json` exactly.
  `tests/unit/test_contract_alignment.py` fails if a field is added, removed or renamed
  on either side.
- Every model validates its own JSON dump against the frozen JSON Schema on
  construction, so the cross-field rules that live only in the schema's `allOf`
  (irreversible ⇒ tier 0, HOLD ⇒ hold block, ACTION_EXECUTED ⇒ approval_id…) are
  enforced through one path: the schema.
- Agent 03's blocks (`economics`, `scores.scorecard`) stay `dict`: 03 owns their
  shape, and the schema `$ref`s their vendored files.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mbos.contracts import schemas

EvidenceTag = Literal["FACT", "INFERENCE", "RECOMMENDATION", "UNKNOWN"]
Reversibility = Literal["reversible", "partially_reversible", "irreversible"]
ItemState = Literal[
    "DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL", "HELD",
    "APPROVED", "REJECTED", "ACTING", "ACTED", "OUTCOME_RECORDED", "LEARNED", "ARCHIVED", "FAILED",
]
FlipCategory = Literal[
    "trailer", "mower", "generator", "welder", "compressor", "tool", "commercial_equipment",
    "mechanical_equipment", "project_vehicle", "other_asset",
]
ServiceCategory = Literal[
    "mobile_repair", "equipment_repair", "drywall_repair", "assembly", "handyman", "smart_home_install",
    "technical_service", "mechanical_service", "other_service",
]
ActionCategory = Literal[
    "message", "offer", "money", "purchase", "publishing", "scheduling", "price_change", "phone_call", "sms",
    "email", "external_commitment",
]
ActionStatus = Literal[
    "drafted", "classified", "pending_approval", "held", "approved", "auto_approved", "rejected", "expired",
    "executing", "executed", "failed", "outcome_recorded", "cancelled_by_freeze",
]
ReceiptType = Literal[
    "ITEM_STATE_CHANGED", "SCORE_RECORDED", "RECOMMENDATION_RECORDED", "ACTION_PROPOSED", "POLICY_DECIDED",
    "APPROVAL_REQUESTED", "APPROVAL_DECIDED", "BUDGET_RESERVED", "BUDGET_COMMITTED", "BUDGET_RELEASED",
    "ACTION_EXECUTING", "ACTION_EXECUTED", "ACTION_FAILED", "OUTCOME_RECORDED", "LESSON_RECORDED",
    "CONFIG_VERSION_BUMPED", "KILL_SWITCH_CHANGED", "GRANT_CREATED", "GRANT_REVOKED", "INJECTION_SUSPECTED",
]
ActorType = Literal["agent", "human", "system", "external"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ContractModel(_Strict):
    """A top-level contract record. Construction validates against the frozen schema."""

    __contract__: ClassVar[str]

    def to_doc(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True, by_alias=True)

    @model_validator(mode="after")
    def _conforms_to_frozen_contract(self) -> "ContractModel":
        schemas.validate(self.__contract__, self.to_doc())
        return self

    @classmethod
    def from_doc(cls, doc: dict[str, Any]):
        """Parse a contract document. Any breach — type-level or schema-level — raises ContractViolation."""
        try:
            return cls.model_validate(doc)
        except ValidationError as e:
            for err in e.errors():
                inner = (err.get("ctx") or {}).get("error")
                if isinstance(inner, schemas.ContractViolation):
                    raise inner from None
            raise schemas.ContractViolation(cls.__contract__, [
                f"{'/'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}" for err in e.errors()
            ]) from None


class Money(BaseModel):
    model_config = ConfigDict(extra="allow")
    amount: float
    currency: str


# ---------------------------------------------------------------- Provenance
class InputUsed(BaseModel):
    model_config = ConfigDict(extra="allow")
    ref: Optional[str] = None
    hash: Optional[str] = None


class Provenance(ContractModel):
    __contract__ = "provenance"
    provenance_id: str
    created_at: datetime
    actor_type: ActorType
    agent_name: Optional[str] = None
    human_actor: Optional[str] = None
    basis: EvidenceTag
    source_uri: Optional[str] = None
    fetched_at: Optional[datetime] = None
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    prompt_hash: Optional[str] = None
    tool_name: Optional[str] = None
    tool_version: Optional[str] = None
    config_version: Optional[str] = None
    approval_id: Optional[str] = None
    trace_id: Optional[str] = None
    inputs_used: Optional[list[InputUsed]] = None
    derived_from: Optional[list[str]] = None
    confidence: Optional[float] = None


# ---------------------------------------------------------------- Item
class ItemSource(_Strict):
    source: str
    source_listing_id: Optional[str] = None
    url: str
    ingestion_method: Literal["api", "json", "email", "rss", "browser", "manual", "inbound_call", "inbound_form"]
    tos_risk: Optional[Literal["low", "med", "high"]] = None
    first_seen_at: datetime
    last_seen_at: Optional[datetime] = None
    raw_ref: Optional[str] = None
    provenance_id: str


class Price(BaseModel):
    model_config = ConfigDict(extra="allow")
    amount: Optional[float] = None
    currency: Optional[str] = None
    type: Optional[Literal["fixed", "auction_current", "starting_bid", "free", "lead_cost", "customer_budget", "quote_requested"]] = None
    buyer_premium_pct: Optional[float] = None


class Location(BaseModel):
    model_config = ConfigDict(extra="allow")
    lat: Optional[float] = None
    lng: Optional[float] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    road_miles_one_way: Optional[float] = None
    geo_tier: Optional[int] = None


class Counterparty(BaseModel):
    model_config = ConfigDict(extra="allow")
    party_id: Optional[str] = None
    role: Optional[Literal["seller", "buyer", "customer", "agency", "other"]] = None
    name: Optional[str] = None
    is_dealer: Optional[bool] = None
    contact_method: Optional[Literal["relay_email", "phone", "in_app", "platform", "gov_poc", "email", "none"]] = None


class Normalized(_Strict):
    title: str
    description: Optional[str] = None
    condition: Optional[Literal["new", "used", "parts", "unknown", "n/a"]] = None
    price: Optional[Price] = None
    ends_at: Optional[datetime] = None
    bid_count: Optional[int] = None
    location: Optional[Location] = None
    counterparty: Optional[Counterparty] = None
    images: Optional[list[str]] = None
    listing_status: Optional[Literal["active", "ended", "sold", "gone", "open", "closed"]] = None
    flags: Optional[list[Literal["underpriced", "zero_bid", "free", "ending_soon", "long_distance", "needs_review", "price_changed", "injection_suspected"]]] = None


class ResearchFinding(_Strict):
    finding: str
    field: Optional[str] = None
    basis: EvidenceTag
    source_uri: Optional[str] = None
    fetched_at: Optional[datetime] = None
    provenance_id: str


class Scores(_Strict):
    scorecard_id: str
    inputs_hash: str
    scorecard: dict[str, Any]


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="allow")
    capability: str
    summary: str
    reversibility: Reversibility
    estimated_cost: Optional[Money] = None


class Recommendation(_Strict):
    recommendation_id: str
    verdict: Literal["YES", "MAYBE", "PASS"]
    proposed_actions: Optional[list[ProposedAction]] = None
    rationale: list[str] = Field(min_length=1)
    confidence: Optional[float] = None
    cheapest_decisive_evidence: Optional[str] = None
    alert: Optional[bool] = None
    provenance_id: str
    expires_at: Optional[datetime] = None


class Item(ContractModel):
    __contract__ = "item"
    item_id: str
    schema_version: Literal["1.0.0"] = "1.0.0"
    type: Literal["flip", "service"]
    category: FlipCategory | ServiceCategory
    subcategory: Optional[str] = None
    opportunity_kind: Optional[Literal["buy_item", "auction_lot", "free_item", "service_lead", "gov_contract"]] = None
    state: ItemState
    created_at: datetime
    updated_at: Optional[datetime] = None
    sources: list[ItemSource] = Field(min_length=1)
    dedup_key: str
    content_hash: Optional[str] = None
    normalized: Normalized
    economics: Optional[dict[str, Any]] = None
    research: Optional[list[ResearchFinding]] = None
    scores: Optional[Scores] = None
    recommendation: Optional[Recommendation] = None
    action_request_ids: Optional[list[str]] = None
    approval_ids: Optional[list[str]] = None
    receipt_ids: Optional[list[str]] = None
    outcome_ids: Optional[list[str]] = None
    provenance_ids: Optional[list[str]] = None


# ---------------------------------------------------------------- ActionRequest
class Target(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: Optional[str] = None
    ref: Optional[str] = None


class ActionRequest(ContractModel):
    __contract__ = "action-request"
    action_request_id: str
    item_id: str
    recommendation_id: Optional[str] = None
    derived_from: Optional[str] = None
    created_at: datetime
    proposed_by: str
    on_behalf_of: Optional[Literal["michael"]] = None
    capability: str
    category: ActionCategory
    payload: dict[str, Any]
    payload_hash: str
    idempotency_key: str
    estimated_cost: Optional[Money] = None
    max_cost: Optional[Money] = None
    reversibility: Reversibility
    untrusted_inputs_present: Optional[bool] = None
    tier: Literal[0, 1, 2, 3]
    policy_decision_ref: Optional[str] = None
    score_ref: Optional[str] = None
    status: ActionStatus
    expires_at: datetime
    provenance_ids: list[str] = Field(min_length=1)
    target: Optional[Target] = None


# ---------------------------------------------------------------- Approval
class AuthContext(BaseModel):
    model_config = ConfigDict(extra="allow")
    method: Optional[str] = None
    session_id: Optional[str] = None
    step_up: Optional[bool] = None


class Modifications(BaseModel):
    model_config = ConfigDict(extra="allow")
    diff: Optional[dict[str, Any]] = None
    new_action_request_id: Optional[str] = None
    new_payload_hash: Optional[str] = None


class Hold(BaseModel):
    model_config = ConfigDict(extra="allow")
    hold_until: Optional[datetime] = None
    wake_on: Optional[list[Literal["time", "new_info", "price_change", "auction_ending", "michael_ping"]]] = None
    renotify_after: Optional[str] = None
    escalate_after: Optional[str] = None


class Approval(ContractModel):
    __contract__ = "approval"
    approval_id: str
    action_request_id: str
    decision: Literal["YES", "NO", "MODIFY", "HOLD"]
    decider: str
    decided_at: datetime
    channel: Literal["telegram", "web", "sms_reply", "email_reply", "cli"]
    auth_context: Optional[AuthContext] = None
    payload_hash_seen: str
    modifications: Optional[Modifications] = None
    hold: Optional[Hold] = None
    reason: Optional[str] = None
    scope: Literal["once", "session", "standing_rule"]
    expires_at: Optional[datetime] = None


# ---------------------------------------------------------------- Receipt
class Actor(_Strict):
    model_config = ConfigDict(extra="allow")
    type: ActorType
    id: str


class BudgetEffect(BaseModel):
    model_config = ConfigDict(extra="allow")
    category: str
    amount: float
    currency: str


class LlmCost(BaseModel):
    model_config = ConfigDict(extra="allow")
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    usd: Optional[float] = None
    trace_id: Optional[str] = None


class EffectorResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider: Optional[str] = None
    provider_msg_id: Optional[str] = None
    status: Optional[str] = None
    dry_run: Optional[bool] = None


class Details(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: Literal["comms", "marketing", "money", "generic"]


class Receipt(ContractModel):
    """A stored receipt. `seq`, `prev_hash` and `row_hash` are assigned by the DB chain trigger."""

    __contract__ = "receipt"
    receipt_id: str
    seq: int
    ts: datetime
    schema_version: Literal["1.0.0"] = "1.0.0"
    type: ReceiptType
    actor: Actor
    intent: str = Field(min_length=1)
    item_id: Optional[str] = None
    action_request_id: Optional[str] = None
    approval_id: Optional[str] = None
    capability: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    effect: Optional[Literal["none", "create", "update", "logical_delete", "send", "pay", "publish", "schedule", "commit"]] = None
    tool_name: Optional[str] = None
    payload_hash: Optional[str] = None
    inputs_hash: Optional[str] = None
    idempotency_key: str
    before_state: Optional[dict[str, Any]] = None
    after_state: Optional[dict[str, Any]] = None
    policy_decision_ref: Optional[str] = None
    budget_effect: Optional[BudgetEffect] = None
    llm_cost: Optional[LlmCost] = None
    effector_response: Optional[EffectorResponse] = None
    provenance_ids: list[str] = Field(min_length=1)
    artifact_hashes: Optional[list[str]] = None
    outcome_id: Optional[str] = None
    details: Optional[Details] = None
    prev_hash: Optional[str]
    row_hash: str

    def to_doc(self) -> dict[str, Any]:
        doc = super().to_doc()
        doc["prev_hash"] = self.prev_hash  # required key; null only for the genesis receipt
        return doc


# ---------------------------------------------------------------- Outcome
class PredictedVsActual(BaseModel):
    model_config = ConfigDict(extra="allow")
    field: str
    predicted: Any = None
    actual: Any


class Realized(BaseModel):
    model_config = ConfigDict(extra="allow")
    revenue: Optional[float] = None
    total_cost: Optional[float] = None
    net_profit: Optional[float] = None
    hours: Optional[float] = None
    days_to_cash: Optional[float] = None


class Attribution(BaseModel):
    model_config = ConfigDict(extra="allow")
    first_touch_source: Optional[str] = None
    first_touch_detail: Optional[str] = None
    self_reported_source: Optional[str] = None
    channel: Optional[str] = None
    utm: Optional[dict[str, Any]] = None


class Outcome(ContractModel):
    __contract__ = "outcome"
    outcome_id: str
    item_id: str
    action_request_id: Optional[str] = None
    scorecard_id: Optional[str] = None
    observed_at: datetime
    kind: Literal[
        "flip_acquired", "flip_sold", "flip_unsold_salvaged", "flip_repair_failed", "flip_passed_missed",
        "service_won", "service_lost", "service_completed", "service_rework", "service_paid",
        "wasted_trip", "message_replied", "message_no_reply", "lead_attributed",
    ]
    predicted_vs_actual: Optional[list[PredictedVsActual]] = None
    realized: Optional[Realized] = None
    attribution: Optional[Attribution] = None
    notes: Optional[str] = None
    provenance_ids: list[str] = Field(min_length=1)


MODELS: dict[str, type[ContractModel]] = {
    "item": Item,
    "action-request": ActionRequest,
    "approval": Approval,
    "receipt": Receipt,
    "provenance": Provenance,
    "outcome": Outcome,
}
