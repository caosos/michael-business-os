import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("dispatcher", Path(__file__).resolve().parents[2] / "tools" / "dispatcher.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def lane(n, ready, state="CLOSED", claimed=""):
    return {"lane": n, "state": state, "claimed": claimed, "ready": [{"id": i, "pri": "P1", "title": "t"} for i in ready]}


REPORT = [lane("02", ["B-30"]), lane("03", ["C-28", "C-29"]), lane("04", ["D-31"]), lane("06", []), lane("07", ["G-22"])]


def test_launches_one_task_per_idle_lane_up_to_the_parallel_limit():
    plan, why = d.plan_launches(REPORT, set(), {}, 0, True, 2)
    assert [(l, t["id"]) for l, t in plan] == [("02", "B-30"), ("03", "C-28")] and why == "ok"
    plan, _ = d.plan_launches(REPORT, {"02"}, {}, 0, True, 2)
    assert [(l, t["id"]) for l, t in plan] == [("03", "C-28")]                      # a lane with a running worker is skipped, one slot left


def test_never_launches_when_the_quota_guard_hourly_cap_or_parallelism_say_no():
    assert d.plan_launches(REPORT, set(), {}, 0, False, 2) == ([], "quota guard")
    assert d.plan_launches(REPORT, {"02", "03"}, {}, 0, True, 2) == ([], "parallelism limit")
    assert d.plan_launches(REPORT, set(), {}, d.MAX_PER_HOUR, True, 2) == ([], "hourly launch limit")


def test_retry_cap_skips_a_task_that_keeps_failing_and_takes_the_next():
    plan, _ = d.plan_launches(REPORT, set(), {"C-28": d.MAX_ATTEMPTS}, 0, True, 3)
    assert ("03", "C-29") in [(l, t["id"]) for l, t in plan]
    plan, _ = d.plan_launches([lane("03", ["C-28"])], set(), {"C-28": d.MAX_ATTEMPTS}, 0, True, 2)
    assert plan == []


def test_the_coordinator_lane_is_never_dispatched():
    plan, _ = d.plan_launches([lane("01", ["A-45"])], set(), {}, 0, True, 2)
    assert plan == []


def test_profile_defaults_are_the_cheapest_capable():
    assert d.profile_for({"id": "C-28", "pri": "P1", "title": "engine"}) == {"kind": "implement", "risk": "medium", "max_turns": 80, "model": None}
    p = d.profile_for({"id": "G-22", "pri": "P1", "title": "QA re-run"})
    assert p["kind"] == "review" and p["model"] == "sonnet" and p["max_turns"] == 100
    assert d.profile_for({"id": "D-31", "pri": "P0", "title": "x"})["risk"] == "high"


def test_workers_started_by_hand_count_as_running():
    ps = ("/x/.venv/bin/python -I tools/worker.py C-28 --lane 03 --kind implement --risk medium\n"
          "python -I tools/worker.py D-31 --lane 04 --max-turns 80\n"
          "grep tools/worker.py --lane 05\n"
          "/x/.venv/bin/python -I tools/dispatcher.py --lane 06\n")
    assert d.lanes_running_in_os(ps) == {"03", "04"}
    plan, _ = d.plan_launches(REPORT, d.lanes_running_in_os(ps), {}, 0, True, 4)
    assert [l for l, _ in plan] == ["02", "07"]                              # 03 and 04 are busy: no duplicates
