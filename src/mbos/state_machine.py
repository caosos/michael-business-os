"""Canonical state machines (ADR-0004, conflict C8: Item flow ⊃ ActionRequest status).

The Item transition table is mirrored in the DB (`mbos.item_state_transitions`, enforced by
the `items_guard` trigger). `tests/unit/test_state_machine.py` asserts the two are identical.
"""

from __future__ import annotations

NON_TERMINAL_ITEM_STATES = (
    "DISCOVERED", "NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL", "HELD",
    "APPROVED", "REJECTED", "ACTING", "ACTED", "OUTCOME_RECORDED", "LEARNED",
)
TERMINAL_ITEM_STATES = ("ARCHIVED", "FAILED")

_ITEM_EDGES = {
    ("DISCOVERED", "NORMALIZED"),
    ("NORMALIZED", "RESEARCHING"), ("NORMALIZED", "SCORED"),
    ("RESEARCHING", "SCORED"), ("SCORED", "RESEARCHING"),
    ("SCORED", "RECOMMENDED"),
    ("RECOMMENDED", "AWAITING_APPROVAL"), ("RECOMMENDED", "RESEARCHING"),
    ("AWAITING_APPROVAL", "APPROVED"), ("AWAITING_APPROVAL", "HELD"), ("AWAITING_APPROVAL", "REJECTED"),
    ("HELD", "AWAITING_APPROVAL"), ("HELD", "APPROVED"), ("HELD", "REJECTED"),
    ("APPROVED", "ACTING"), ("ACTING", "ACTED"),
    ("ACTED", "OUTCOME_RECORDED"), ("OUTCOME_RECORDED", "LEARNED"),
}
ITEM_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    _ITEM_EDGES | {(s, t) for s in NON_TERMINAL_ITEM_STATES for t in TERMINAL_ITEM_STATES}
)


class IllegalTransition(ValueError):
    pass


def check_item_transition(from_state: str, to_state: str) -> None:
    if (from_state, to_state) not in ITEM_TRANSITIONS:
        raise IllegalTransition(f"illegal item transition {from_state} -> {to_state}")


# ActionRequest status (Agent 05 §4.3). MODIFY closes the old request as `rejected` with an
# intent naming its successor; the contract has no `superseded` status (see integration notes).
ACTION_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("drafted", "classified"),
    ("classified", "pending_approval"), ("classified", "rejected"),
    ("pending_approval", "approved"), ("pending_approval", "rejected"), ("pending_approval", "held"),
    ("pending_approval", "expired"), ("pending_approval", "cancelled_by_freeze"),
    ("held", "approved"), ("held", "rejected"), ("held", "pending_approval"), ("held", "expired"),
    ("held", "cancelled_by_freeze"),
    ("approved", "executing"), ("approved", "cancelled_by_freeze"), ("approved", "expired"),
    ("executing", "executed"), ("executing", "failed"), ("executing", "cancelled_by_freeze"),
    ("executed", "outcome_recorded"),
})


def check_action_transition(from_status: str, to_status: str) -> None:
    if (from_status, to_status) not in ACTION_TRANSITIONS:
        raise IllegalTransition(f"illegal action-request transition {from_status} -> {to_status}")
