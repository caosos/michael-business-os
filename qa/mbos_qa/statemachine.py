"""Item business-flow state machine (integration doc §4; ADR-0004 rule 4). Owner: Agent 01.

DISCOVERED → NORMALIZED → RESEARCHING ⇄ SCORED → RECOMMENDED → AWAITING_APPROVAL →
  {APPROVED → ACTING → ACTED → OUTCOME_RECORDED → LEARNED} | HELD | REJECTED.
ARCHIVED (from PASS or NO) and FAILED are reachable from any state.
QA interpretation (flagged in report): HELD → AWAITING_APPROVAL on wake; REJECTED → ARCHIVED.
"""
ITEM_EDGES = {
    "DISCOVERED": {"NORMALIZED"},
    "NORMALIZED": {"RESEARCHING"},
    "RESEARCHING": {"SCORED"},
    "SCORED": {"RESEARCHING", "RECOMMENDED"},
    "RECOMMENDED": {"AWAITING_APPROVAL", "RESEARCHING"},
    "AWAITING_APPROVAL": {"APPROVED", "HELD", "REJECTED"},
    "HELD": {"AWAITING_APPROVAL"},
    "APPROVED": {"ACTING"},
    "ACTING": {"ACTED"},
    "ACTED": {"OUTCOME_RECORDED"},
    "OUTCOME_RECORDED": {"LEARNED"},
    "REJECTED": set(),
    "LEARNED": set(),
    "ARCHIVED": set(),
    "FAILED": set(),
}
TERMINAL = {"ARCHIVED", "FAILED", "LEARNED"}


class IllegalTransition(Exception):
    pass


def check_item_transition(old: str, new: str) -> None:
    if new in ("ARCHIVED", "FAILED") and old not in ("ARCHIVED", "FAILED"):
        return
    if new not in ITEM_EDGES.get(old, set()):
        raise IllegalTransition(f"{old} -> {new}")
