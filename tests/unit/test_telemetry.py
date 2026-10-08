import json

import pytest

from mbos import telemetry as T

RESULT = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 12345, "duration_api_ms": 9000, "num_turns": 7,
          "result": "done", "session_id": "11111111-2222-3333-4444-555555555555", "total_cost_usd": 0.42,
          "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40},
          "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 10}}}
ROUTE = {"model": "sonnet", "tier": "default", "rule_id": "R-SONNET", "reason": "default"}


def row(**kw):
    base = dict(task_id="X-1", lane="01", route=ROUTE, started_at="2026-10-08T00:00:00Z", ended_at="2026-10-08T00:01:00Z", exit_code=0, result=RESULT)
    base.update(kw)
    return T.run_row(**base)


def test_parse_result_fields_and_unknowns():
    p = T.parse_result(RESULT)
    assert p["num_turns"] == 7 and p["cost_estimate_usd"] == 0.42 and p["models_used"] == ["claude-sonnet-5-5"]
    q = T.parse_result({})
    assert all(v is None for v in q.values())            # nothing invented
    assert T.parse_result([{"type": "system"}, RESULT])["session_id"] == RESULT["session_id"]   # stream-json


def test_row_marks_cost_as_estimate_and_success():
    r = row()
    assert r["success"] is True and r["cost_is_estimate_not_a_bill"] is True and r["cost_estimate_usd"] == 0.42
    assert row(exit_code=1)["success"] is False
    assert row(result={})["success"] is False             # unknown is_error is not success


def test_chain_appends_and_detects_tampering(tmp_path):
    p = tmp_path / "w.jsonl"
    T.append(row(), p); T.append(row(task_id="X-2"), p)
    assert T.verify(T.read(p)) == []
    lines = p.read_text().splitlines()
    d = json.loads(lines[0]); d["success"] = False
    p.write_text(json.dumps(d) + "\n" + lines[1] + "\n")
    assert any("edited" in e for e in T.verify(T.read(p)))
    p.write_text(lines[1] + "\n")
    assert any("prev_hash" in e for e in T.verify(T.read(p)))


def test_summary_and_manual_quota(tmp_path):
    p = tmp_path / "w.jsonl"
    s0 = T.summarize(T.read(p))
    assert s0["quota"]["week_all_pct"] is None and "UNKNOWN" in s0["quota"]["source"]
    T.append(row(), p); T.append(row(escalated_from="sonnet", retry=1, exit_code=1), p)
    T.quota_snapshot(session_pct=75, week_all_pct=38, week_fable_pct=0, resets="in 2h", path=p)
    s = T.summarize(T.read(p))
    assert s["runs"] == 2 and s["failed"] == 1 and s["escalations"] == 1 and s["retries"] == 1
    assert s["model_mix"] == {"sonnet": 2} and s["quota"]["week_all_pct"] == 38 and s["quota"]["source"] == "manual"
    assert s["chain_errors"] == []
    with pytest.raises(ValueError):
        T.quota_snapshot(session_pct=140, path=p)


def test_real_stream_json_probe_gives_result_and_quota(tmp_path):
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "fixtures" / "claude_stream_json_probe.jsonl").read_text()
    result, rl = T.parse_stream(text)
    assert result["type"] == "result" and result["num_turns"] == 1 and "claude-sonnet-5-5" in result["modelUsage"]
    p = tmp_path / "q.jsonl"
    snap = T.quota_from_rate_limit(rl, path=p)
    assert snap["session_pct"] == 83.0 and snap["week_all_pct"] == 39.0 and snap["source"] == "claude_code_rate_limit_event"
    assert snap["week_fable_pct"] is None                   # no supported source for per-model weekly %
    assert snap["session_resets_at"].endswith("Z")
    assert T.summarize(T.read(p))["quota"]["session_pct"] == 83.0


def test_no_rate_limit_info_records_nothing(tmp_path):
    p = tmp_path / "q.jsonl"
    assert T.quota_from_rate_limit(None, path=p) is None
    assert T.quota_from_rate_limit({"unifiedWindows": {"five_hour": {"utilization": 7}}}, path=p) is None   # out of 0..1: rejected
    assert T.read(p) == []


def test_quota_guard_blocks_only_on_a_fresh_supported_reading_over_the_limit(tmp_path):
    from datetime import datetime, timedelta, timezone
    from mbos.router import load_policy
    pol = load_policy()
    now = datetime.now(timezone.utc)
    assert T.quota_guard(pol, [], now=now)["allow"]                                   # no reading: UNKNOWN is not a stop
    def snap(pct, week, age_min, source="claude_code_rate_limit_event"):
        return {"kind": "quota_snapshot", "source": source, "session_pct": pct, "week_all_pct": week, "session_resets_at": "x", "week_resets_at": "y",
                "at": (now - timedelta(minutes=age_min)).isoformat().replace("+00:00", "Z")}
    assert not T.quota_guard(pol, [snap(95, 40, 5)], now=now)["allow"]
    assert not T.quota_guard(pol, [snap(40, 95, 5)], now=now)["allow"]
    assert T.quota_guard(pol, [snap(89, 40, 5)], now=now)["allow"]
    assert T.quota_guard(pol, [snap(99, 99, 600)], now=now)["allow"]                  # stale reading never blocks
    assert T.quota_guard(pol, [snap(99, 99, 5, source="manual")], now=now)["allow"]   # manual entries are not used for gating


def test_multiple_result_events_are_merged_and_the_report_is_found():
    done = '{"task":"T-1","status":"DONE","commit":"abc","tests":"3 passed","notes":"x"}'
    first = {"type": "result", "is_error": False, "num_turns": 40, "duration_ms": 600000, "duration_api_ms": 500000, "total_cost_usd": 1.1,
             "result": "work done\n" + done, "session_id": "s", "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "x"}}]}
    trailing = {"type": "result", "is_error": False, "num_turns": 1, "duration_ms": 2000, "duration_api_ms": 1500, "total_cost_usd": 1.3,
                "result": "background task finished", "session_id": "s"}
    text = "\n".join(json.dumps(e) for e in (first, trailing))
    res, _ = T.parse_stream(text)
    p = T.parse_result(res)
    assert p["num_turns"] == 41 and p["duration_ms"] == 602000 and p["cost_estimate_usd"] == 1.3     # cost is cumulative: max, not sum
    assert p["worker_report"]["status"] == "DONE" and p["permission_denials"] == 1
    # order reversed (report arrives in the last event) behaves the same
    res2, _ = T.parse_stream("\n".join(json.dumps(e) for e in (trailing, first)))
    assert T.parse_result(res2)["worker_report"]["status"] == "DONE"
