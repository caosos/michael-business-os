"""Lane C (Agent 03) economics engine behind `Scorer`.

Install the engine from Agent 03's branch (read-only, no merge), e.g.:
    uv pip install "mbos-economics @ git+file://<repo>@<agent-03 commit>#subdirectory=economics"
and pass `config_dir` pointing at a checkout of `economics/config/` from the same commit
(the engine resolves configs relative to its source tree, which an installed wheel lacks).

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
