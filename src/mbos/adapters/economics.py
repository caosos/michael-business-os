"""Lane C (Agent 03) economics engine behind `Scorer`.

Install the engine from Agent 03's branch (read-only, no merge), e.g.:
    uv pip install "mbos-economics @ git+file://<repo>@<agent-03 commit>#subdirectory=economics"
Since lane C 1044ed5 the config ships inside the wheel, so `config_dir` is optional (pass it only to pin a
config directory explicitly).

Mapping (agent-01 integration review, 2026-10-07):
- `score_item(item, cfg, scored_at)` → ScoreResult; 03's deterministic scr_/rec_ ids are kept (replay).
- `scored_at` must be deterministic for replay: the Item's `updated_at` (else `created_at`), never wall-clock.
- 03 proposes no actions; the spine's ActionPlanner does.
- Items without `economics` (every lane-B Item today) raise InputError → MAYBE "needs research",
  so the item parks in RESEARCHING until a RESEARCH/estimate step fills `Item.economics`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from mbos.interfaces import ScoreResult


class EconomicsEngineScorer:
    def __init__(self, config_dir: Optional[str | Path] = None, version: Optional[str] = None):
        from mbos_economics import __version__ as engine_version  # lane C package
        from mbos_economics.config import load_config

        kwargs = {"config_dir": Path(config_dir)} if config_dir else {}
        self.cfg = load_config(version, **kwargs)
        self.engine_version = engine_version

    def score(self, item: dict[str, Any]) -> ScoreResult:
        from mbos_economics.engine import score_item
        from mbos_economics.inputs import InputError

        scored_at = item.get("updated_at") or item["created_at"]
        try:
            out = score_item(item, self.cfg, scored_at)
        except InputError as e:
            reason = f"Economics inputs missing or invalid: {e}"
            card = {"scoring_config_version": self.cfg.version, "derived": {}, "sub_scores": {}, "composite": 0,
                    "decision": "MAYBE", "gates": {}, "reasons": [reason],
                    "cheapest_decisive_evidence": "Economics estimates (comps, repair/job scope) from RESEARCH"}
            from mbos.hashing import sha256_of
            return ScoreResult(
                scorecard=card, inputs_hash=sha256_of({"item_id": item.get("item_id"), "economics": None,
                                                       "scoring_config_version": self.cfg.version}),
                verdict="MAYBE", rationale=[reason], confidence=0.0, scoring_config_version=self.cfg.version,
                tool_name="mbos_economics.engine", tool_version=self.engine_version,
                cheapest_decisive_evidence=card["cheapest_decisive_evidence"])
        rec, scores = out["recommendation"], out["scores"]
        return ScoreResult(
            scorecard=scores["scorecard"], inputs_hash=scores["inputs_hash"], verdict=rec["verdict"],
            rationale=rec["rationale"], confidence=rec["confidence"], scoring_config_version=self.cfg.version,
            tool_name="mbos_economics.engine", tool_version=self.engine_version,
            cheapest_decisive_evidence=rec.get("cheapest_decisive_evidence"), alert=bool(rec.get("alert")),
            scorecard_id=scores["scorecard_id"], recommendation_id=rec["recommendation_id"],
        )


class EconomicsResearcher:
    """Lane C's RESEARCH step (`mbos_economics.comps_feed.research_step`) behind `Researcher` (task A-05).

    `comps_source(item) -> (comp_records, provenance_records)` is lane B's sold-comps source (Agent 02,
    `mbos_discovery.comps`); in tests, 03's `load_fixture_comps`. `as_of` is the Item's own timestamp, never
    wall-clock, so the step replays exactly.
    """

    def __init__(self, comps_source):
        self.comps_source = comps_source

    def research(self, item: dict[str, Any]):
        from mbos_economics import __version__ as engine_version
        from mbos_economics.comps_feed import research_step

        from mbos.interfaces import ResearchResult

        as_of = item.get("updated_at") or item["created_at"]
        comps, prov = self.comps_source(item)
        out = research_step(item, comps, prov, as_of)
        new = out["item"]
        score = None
        if out["proposed_next_state"] == "SCORED":
            sc, rec = new["scores"], new["recommendation"]
            score = ScoreResult(
                scorecard=sc["scorecard"], inputs_hash=sc["inputs_hash"], verdict=rec["verdict"],
                rationale=rec["rationale"], confidence=rec.get("confidence", 0.0),
                scoring_config_version=sc["scorecard"]["scoring_config_version"],
                tool_name="mbos_economics.engine", tool_version=engine_version,
                cheapest_decisive_evidence=rec.get("cheapest_decisive_evidence"), alert=bool(rec.get("alert")),
                scorecard_id=sc["scorecard_id"], recommendation_id=rec["recommendation_id"])
        return ResearchResult(next_state=out["proposed_next_state"], economics=new.get("economics"),
                              research=new.get("research") or [], provenance_records=out["provenance_records"],
                              score=score, gaps=[_gap_text(g) for g in out["estimate"].get("gaps") or []])


def _gap_text(g: Any) -> str:
    """Lane C gaps are {code, blocking, detail}; the spine carries readable strings (blocking ones first)."""
    if isinstance(g, dict):
        return f"{'BLOCKING ' if g.get('blocking') else ''}{g.get('code', 'gap')}: {g.get('detail', '')}".strip(": ")
    return str(g)


class EconomicsEnricher:
    """Lane C's card enrichment (`mbos_economics.enrich.build_enrichment`, C-15) behind `Enricher` (A-20).

    Persists lane C's provenance FIRST, then each block through `spine.record_enrichment` (atomic append). Blocks:
    economics, logistics, seasonality, why. Idempotent (same content = no-op). Whatever the evidence cannot support is
    omitted by lane C, so the card prints UNKNOWN. `as_of` is the Item's own timestamp, never wall-clock.
    """

    AGENT = "agent-03-economics"
    skipped_notes: list = []

    def __init__(self, profile: dict | None = None):
        from mbos import card

        self.profile = profile if profile is not None else card.load_profile()

    def enrich(self, conn, spine, item_id: str) -> int:
        from mbos_economics.config import load_config
        from mbos_economics.enrich import build_enrichment, load_seasonality
        from mbos_economics.estimate import load_priors

        item = spine.read_item(conn, item_id)
        if item["state"] in ("ARCHIVED", "FAILED"):
            return 0
        card_ = (item.get("scores") or {}).get("scorecard")
        if not card_ or "engine_version" not in card_:  # lane C enriches only what lane C's own engine scored
            return 0
        la = self._listing_activity(conn, item)
        as_of = card_.get("computed_at") or item["created_at"]  # stable once scored (updated_at moves on every change)
        e = build_enrichment(item, as_of, cfg=load_config(), priors=load_priors(),
                             seasonality=load_seasonality(), profile=self.profile, listing_activity=la)
        n = 0
        if e.get("blocks"):
            pid = spine.record_lane_provenance(conn, e["provenance"])
            for block, data in e["blocks"].items():
                spine.record_enrichment(conn, item_id, block, data, pid, summary=f"lane C {block}", agent=self.AGENT)
            n += len(e["blocks"])
        n += self._value_add(conn, spine, item, as_of, la)
        return n

    def _value_add(self, conn, spine, item: dict, as_of: str, la) -> int:
        """C-16: plan from the deal's own numbers + SOURCED model-specific risks (CPSC recalls etc.). Whatever matches
        no sourced knowledge is omitted, so the card prints UNKNOWN."""
        from mbos_economics.config import load_config
        from mbos_economics.valueadd import build_value_add, load_kb, load_manual_notes_lenient, merge_manual

        from mbos.card import enrichment_from_item

        mm = (enrichment_from_item(conn, item).get("make_model") or {}).get("value")
        kb = load_kb()
        doc = spine.operator_notes_document(conn)  # Michael's own notes (RECOMMENDATION); a sourced recall stays first
        if doc.get("notes"):
            # lenient: one bad stored note must not disable the others (03 D-17 review); rejected ones are skipped
            good, problems = load_manual_notes_lenient(doc)
            if problems:  # never silent: a stored note that fails the lint is skipped AND reported
                import logging

                logging.getLogger("mbos.enrich").warning("operator notes skipped by lane C loader: %s", problems)
                self.skipped_notes = problems
            kb = merge_manual(kb, good)
        v = build_value_add(item, as_of, cfg=load_config(), kb=kb, make_model=mm if isinstance(mm, str) else None,
                            model_years=self._model_years(item))
        if not v.get("block"):
            return 0
        pid = spine.record_lane_provenance(conn, v["provenance"])
        spine.record_enrichment(conn, item["item_id"], "value_add", v["block"], pid, summary="lane C value-add", agent=self.AGENT)
        return 1

    @staticmethod
    def _model_years(item: dict):
        """Shorthand model years ('18, MY2018) from the listing title, as INFERENCE with quoted evidence (lane B's extractor, P-02-14).
        Optional: without lane B's package, or when nothing is found, lane C falls back to its own four-digit-year matching."""
        try:
            from mbos_discovery.model_years import extract_model_years
        except ImportError:
            return None
        title = ((item.get("normalized") or {}).get("title")) or ""
        try:
            found = extract_model_years(title)
        except Exception:  # an extractor bug must never take enrichment down
            return None
        return found or None

    @staticmethod
    def _listing_activity(conn, item: dict):
        from mbos.card import enrichment_from_item

        return enrichment_from_item(conn, item).get("listing_activity")
