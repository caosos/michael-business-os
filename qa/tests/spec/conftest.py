"""Spec suite: A1–A10 written against an implementation-neutral QA facade and run against a REAL
implementation chosen by MBOS_QA_IMPL (G-02: `mbos_qa.impl_spine:build` = Agent 01's spine on PostgreSQL 16 + DBOS).
With the default `mock`, this directory is not collected; `tests/test_a*.py` cover the reference mocks instead."""
import importlib
import os

import pytest

IMPL = os.environ.get("MBOS_QA_IMPL", "mock")
collect_ignore_glob = ["test_*.py"] if IMPL == "mock" else []

FLIP_YES, SERVICE_YES, SERVICE_MAYBE, FLIP_PASS = "FIX-TRAILER-1", "FIX-LEAD-SMARTHOME-1", "FIX-LEAD-DRYWALL-1", "FIX-MOWER-1"


@pytest.fixture(scope="session")
def qa(tmp_path_factory):
    mod, _, fn = IMPL.partition(":")
    q = getattr(importlib.import_module(mod), fn)(tmp_path_factory.mktemp("spec"))
    assert not q.is_mock, "the spec suite only reports against a real implementation"
    yield q
    q.close()


@pytest.fixture
def led(qa):
    db = qa.ledger()
    yield db
    db.dispose()


@pytest.fixture
def pending_flip(qa):
    item_id = qa.discover(FLIP_YES)
    return item_id, qa.pending(item_id)


def effector_calls_for(qa, areq_id, engine=None) -> int:
    return len(qa.effector_rows(engine, areq_id))


def invocations(qa, areq) -> int:
    from mbos_qa.impl_spine import INVOCATIONS

    return INVOCATIONS.get(areq["idempotency_key"], 0)
