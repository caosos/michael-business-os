"""Integration interfaces between lanes (round two).

Agent 01 owns these signatures. Each specialist lane implements its Protocol and
registers it in `mbos.runtime.Components`. The reference implementations in
`mbos.reference` exist only so the spine and the A1–A10 suite run end to end; each is
labelled with the lane that replaces it.

| Protocol           | Owner lane                 | Reference stub                          |
|--------------------|----------------------------|-----------------------------------------|
| SourceAdapter      | B Discovery (Agent 02)     | reference.fixture_adapter.FixtureSourceAdapter |
| Normalizer         | B Discovery (Agent 02)     | reference.fixture_adapter.FixtureNormalizer    |
| Deduper            | B Discovery (Agent 02)     | reference.fixture_adapter.ExactKeyDeduper      |
| Researcher         | C Economics (Agent 03) + B comps | adapters.economics.EconomicsResearcher (real) |
| Enricher           | B (02 listing/seller), C (03 economics/logistics/seasonality/why/value-add) | adapters.economics.EconomicsEnricher |
| Scorer             | C Economics (Agent 03)     | adapters.economics.EconomicsEngineScorer (real) / reference.placeholder_scorer |
| ActionPlanner      | 06 Comms / 07 Marketing    | reference.action_planner.DefaultActionPlanner  |
| PolicyDecisionPoint| E Governance (Agent 05)    | reference.governance.DenyByDefaultPDP          |
| Gateway            | E Governance (Agent 05)    | reference.governance.ReferenceGateway          |
| Effector           | 06 Comms / 07 Marketing    | reference.governance.DryRunEffector            |
| KillSwitch         | E Governance (Agent 05)    | reference.governance.TableKillSwitch           |
| LLMBudget          | E Governance (Agent 05)    | reference.governance.LedgerLLMBudget           |
| Notifier           | F Operator UI (06 UX spec) | reference.notify.OutboxNotifier                |

Rules every implementation must follow:
1. Inputs from listings, messages and web pages are UNTRUSTED data. They never grant authority.
2. Nothing here performs an external side effect except an `Effector`, and only when called by
   the `Gateway` after all guard checks pass. In the MVP every Effector is dry-run.
3. Return plain JSON-serialisable values (they are checkpointed by DBOS).
4. Anything consequential returns enough for the caller to write provenance (tool, version,
   source URI + fetched_at, or model + version + prompt hash).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

import sqlalchemy as sa


# ---------------------------------------------------------------- B: discovery
@dataclass(frozen=True)
class RawListing:
    """One as-discovered record. `payload` is stored verbatim in the artifact store (`raw_ref`)."""

    source: str
    source_listing_id: Optional[str]
    url: str
    fetched_at: str  # RFC 3339
    ingestion_method: str  # item.schema.json sources[].ingestion_method
    tos_risk: str  # low | med | high (ADR-02-0202)
    payload: dict[str, Any]


@dataclass(frozen=True)
class NormalizedListing:
    """Agent 02's raw → Item v1 mapping, minus ids/state/provenance (the spine assigns those)."""

    type: str  # flip | service
    category: str
    dedup_key: str
    normalized: dict[str, Any]  # Item.normalized
    subcategory: Optional[str] = None
    opportunity_kind: Optional[str] = None
    content_hash: Optional[str] = None
    economics: Optional[dict[str, Any]] = None  # 03 input estimates when the source supplies them
    match_hints: Optional[dict[str, Any]] = None  # lane B dedup hints (e.g. {"phash": [...], "contact_fp": ...})


@runtime_checkable
class SourceAdapter(Protocol):
    name: str
    ingestion_method: str
    tos_risk: str

    def fetch(self, since: Optional[str] = None) -> list[RawListing]:
        """Read-only collection. Must honour ADR-02-0202 tiers and the do-not-automate list."""


@runtime_checkable
class Deduper(Protocol):
    def is_duplicate(self, existing_item: dict[str, Any], candidate: NormalizedListing,
                     context: Optional[dict[str, Any]] = None) -> bool:
        """Called only for existing Items that share the candidate's `dedup_key`. The key is a BLOCKING
        bucket (Agent 02: category|priceband|geocell), never an identity: equal keys alone must not merge.

        `context` (A-14) = {"source", "source_listing_id", "url", "fetched_at", "match_hints"} of the candidate
        sighting, so lane B can apply its relist and photo (pHash) rules on the spine path."""


@runtime_checkable
class Normalizer(Protocol):
    def normalize(self, raw: RawListing) -> Optional[NormalizedListing]:
        """Map one raw listing to Item v1 fields; None = not an opportunity (dropped, still receipted)."""


# ---------------------------------------------------------------- C: economics
@dataclass(frozen=True)
class ScoreResult:
    """Agent 03 output. `scorecard` must validate against vendor/agent-03/scorecard.schema.json."""

    scorecard: dict[str, Any]
    inputs_hash: str  # sha256 of canonical(economics + research ids + scoring_config_version)
    verdict: str  # YES | MAYBE | PASS (machine verdict, NOT Michael's decision)
    rationale: list[str]
    confidence: float
    scoring_config_version: str
    tool_name: str
    tool_version: str
    proposed_actions: list[dict[str, Any]] = field(default_factory=list)  # Item.recommendation.proposed_actions
    cheapest_decisive_evidence: Optional[str] = None
    alert: bool = False
    # Lane C may mint deterministic ids (replay, AT-1). When set, the spine stores them as-is.
    scorecard_id: Optional[str] = None
    recommendation_id: Optional[str] = None


@dataclass(frozen=True)
class ResearchResult:
    """Lane C's RESEARCH step (A-05). Pure: the spine persists provenance and owns every transition."""

    next_state: str  # SCORED | RESEARCHING
    economics: Optional[dict[str, Any]]  # Item.economics after estimation (None if insufficient)
    research: list[dict[str, Any]]  # Item.research[] entries (each cites a provenance_id)
    provenance_records: list[dict[str, Any]]  # full Provenance v1 docs to persist (comps, estimate, score)
    score: Optional[ScoreResult]  # set when next_state == SCORED
    gaps: list[str] = field(default_factory=list)  # what to research next when insufficient


@runtime_checkable
class Researcher(Protocol):
    def research(self, item: dict[str, Any]) -> ResearchResult:
        """Gather evidence (comps via lane B), estimate economics, and score if sufficient. Deterministic."""


@runtime_checkable
class Enricher(Protocol):
    def enrich(self, conn: sa.Connection, spine: Any, item_id: str) -> int:
        """Attach this lane's card-enrichment blocks (ADR-0011) to the Item inside the caller's transaction, using
        `spine.record_lane_provenance` and `spine.record_enrichment`. MUST be idempotent and MUST omit anything the
        evidence cannot support (the card prints UNKNOWN). Returns the number of blocks attached."""


@runtime_checkable
class Scorer(Protocol):
    def score(self, item: dict[str, Any]) -> ScoreResult:
        """Pure and replayable: the same Item inputs must reproduce the same inputs_hash and scorecard (AT-1, C22)."""


@runtime_checkable
class ActionPlanner(Protocol):
    def plan(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        """For a YES item whose recommendation carries no proposed_actions (lane C proposes none), return
        Item.recommendation.proposed_actions entries {capability, summary, reversibility, estimated_cost}.
        Drafting content is lane 06 (comms) / 07 (publishing); the spine owns turning them into requests."""


# ---------------------------------------------------------------- E: governance
@dataclass(frozen=True)
class PolicyDecision:
    decision: str  # require_approval | deny | allow  (MVP: never allow — MICHAEL_DECISIONS #5)
    tier: int
    category: str
    reason: str
    policy_version: str


@runtime_checkable
class PolicyDecisionPoint(Protocol):
    def decide(self, action_request: dict[str, Any]) -> PolicyDecision: ...


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    checks: dict[str, bool]
    reason: str
    effector_response: dict[str, Any]
    frozen: bool = False  # True when denial came from a kill switch (→ cancelled_by_freeze)


@runtime_checkable
class KillSwitch(Protocol):
    def is_clear(self, conn: sa.Connection, *, capability: str, agent_id: str) -> tuple[bool, str]:
        """Fail closed: any error, missing flag or malformed flag means NOT clear (A9)."""


@runtime_checkable
class Effector(Protocol):
    name: str
    dry_run: bool

    def execute(self, engine: sa.Engine, action_request: dict[str, Any]) -> dict[str, Any]:
        """Perform the action exactly once per `action_request.idempotency_key` and return an
        effector_response {provider, provider_msg_id, status, dry_run}. A repeat call with the same
        key must return the original response without acting again (A5)."""


@runtime_checkable
class Gateway(Protocol):
    def execute(self, engine: sa.Engine, action_request_id: str, approval_id: str) -> GuardResult:
        """Run the 8 execution-guard checks (ADR-0005) and, only if all pass, call the Effector."""


@runtime_checkable
class LLMBudget(Protocol):
    def authorize(self, conn: sa.Connection, agent_id: str, est_usd: float) -> None:
        """Raise BudgetExceeded when the agent's cap would be exceeded (A8)."""

    def record(self, conn: sa.Connection, agent_id: str, usd: float, trace_id: Optional[str] = None) -> None: ...


class BudgetExceeded(RuntimeError):
    pass


# ---------------------------------------------------------------- F: operator UI
@runtime_checkable
class Notifier(Protocol):
    def notify(self, conn: sa.Connection, *, kind: str, item_id: str, action_request_id: Optional[str],
               summary: str) -> None:
        """Queue an operator notification in the same transaction as its receipt (outbox)."""
