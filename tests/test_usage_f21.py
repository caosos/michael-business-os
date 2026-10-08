"""F-21: the usage / agent dashboard over `mbos.telemetry` (ADR-0014). Rendered from fixture files in tmp_path."""

from __future__ import annotations

import json

from mbos import telemetry
from operator_ui import usage_view as uv
from tests.test_operator_ui import req

QUEUE = """| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| F-21 | P1 | Usage dashboard | A-30 | CLAIMED | 06 | x |
| F-20 | P2 | Intake flow | none | READY | 06 | x |
| A-29 | P1 | Dispatcher <script>x</script> | A-30 | **BLOCKED**: waiting | 01 | x |
| A-30 | P0 | Launcher | none | **DONE** (this push) | 01 | x |
"""


def run(task, model, *, turns=7, cost=0.5, ended="2026-10-07T10:00:00Z", ok=True, esc=None, retry=0):
    result = {"type": "result", "num_turns": turns, "total_cost_usd": cost, "duration_ms": 60000, "is_error": not ok,
              "result": json.dumps({"task": task, "status": "DONE", "commit": "abc", "tests": "1/0", "notes": "n"})}
    return telemetry.run_row(task_id=task, lane="06", route={"model": model, "tier": "t", "rule_id": "r", "reason": "x"},
                             started_at="2026-10-07T09:00:00Z", ended_at=ended, exit_code=0 if ok else 1, result=result,
                             retry=retry, escalated_from=esc, head_before="a", head_after="b")


def fixture(tmp_path, *, quota=True):
    p = tmp_path / "worker_runs.jsonl"
    telemetry.append(run("F-21", "sonnet"), p)
    telemetry.append(run("F-20", "opus", turns=3, ended="2026-10-08T10:00:00Z", esc="sonnet", retry=1), p)
    if quota:
        telemetry.append({"kind": "quota_snapshot", "at": "2026-10-08T11:00:00Z", "session_pct": 12.5, "week_all_pct": 40.0, "week_fable_pct": None,
                          "source": "claude_code_rate_limit_event", "entered_by": "claude-code"}, p)
    return p


def test_fixture_renders_every_figure_with_its_source(tmp_path):
    fixture(tmp_path)
    q = tmp_path / "q.md"
    q.write_text(QUEUE)
    h = uv.render_page(uv.load(str(tmp_path)), uv.queue_states(str(q)))
    assert "sonnet 1" in h and "opus 1" in h and "fable 0" in h and "haiku 0" in h            # model mix
    assert "60 s" in h and "10 / 5.0" in h and "1 / 1" in h                                    # avg duration, turns, escalations/retries
    assert "2026-10-07: 1" in h and "2026-10-08: 1" in h                                       # throughput per day
    assert "12.5%" in h and "40.0%" in h and "claude_code_rate_limit_event" in h               # quota with its source
    assert "Weekly Fable</td><td><b class='unk'>UNKNOWN" in h and "Contributor splits" in h
    assert "<b>1</b> active" in h and "<b>1</b> queued" in h and "<b>1</b> blocked" in h      # DONE rows are not counted
    assert "&lt;script&gt;" in h and "<script>" not in h                                       # queue text escaped


def test_cost_is_labelled_a_claude_code_estimate_not_a_bill(tmp_path):
    fixture(tmp_path)
    h = uv.render_page(uv.load(str(tmp_path)))
    assert "Claude Code estimate, not a bill" in h and "$1.00" in h
    i = h.index("$1.00")
    assert "Claude Code estimate, not a bill" in h[i - 80:i + 160]                              # the label sits with the number


def test_empty_and_missing_telemetry_are_all_unknown_and_do_not_crash(tmp_path):
    (tmp_path / "worker_runs.jsonl").write_text("")
    for d in (tmp_path, tmp_path / "nonexistent"):
        h = uv.render_page(uv.load(str(d)), uv.queue_states(None))
        assert "every figure below is UNKNOWN" in h and "UNKNOWN" in h and "$" not in h and "0 s" not in h
        assert "Tasks" in h and "Quota" in h
    assert not (tmp_path / "nonexistent").exists()                                              # read-only: nothing created


def test_missing_figures_are_unknown_not_zero(tmp_path):
    p = tmp_path / "worker_runs.jsonl"
    r = run("F-21", "sonnet")
    r.update(num_turns=None, cost_estimate_usd=None, duration_ms=None)
    telemetry.append({k: v for k, v in r.items() if k not in ("prev_hash", "row_hash")}, p)
    h = uv.render_page(uv.load(str(tmp_path)))
    assert "Average duration</td><td><b class='unk'>UNKNOWN" in h and "Turns (total / average)</td><td><b class='unk'>UNKNOWN" in h
    assert "Claude Code estimate, not a bill" in h and "$0" not in h


def test_edited_chain_is_shown_loudly_and_hides_the_figures(tmp_path):
    p = fixture(tmp_path)
    rows = p.read_text().splitlines()
    d = json.loads(rows[0])
    d["num_turns"] = 999
    rows[0] = json.dumps(d, sort_keys=True)
    p.write_text("\n".join(rows) + "\n")
    h = uv.render_page(uv.load(str(tmp_path)))
    assert "flash err" in h and "FAILED VERIFICATION" in h and "row 0" in h and "999" not in h and "Worker runs" not in h


def test_garbage_file_is_reported_not_a_crash(tmp_path):
    (tmp_path / "worker_runs.jsonl").write_text("not json\n")
    h = uv.render_page(uv.load(str(tmp_path)))
    assert "flash err" in h and "unreadable" in h


def test_hostile_text_in_rows_is_escaped(tmp_path):
    p = tmp_path / "worker_runs.jsonl"
    r = run("<script>alert(1)</script>", "<img src=x>")
    telemetry.append({k: v for k, v in r.items() if k not in ("prev_hash", "row_hash")}, p)
    h = uv.render_page(uv.load(str(tmp_path)))
    assert "<script>" not in h and "<img" not in h and "&lt;script&gt;" in h


def test_env_selects_the_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_TELEMETRY_DIR", str(tmp_path))
    assert uv.telemetry_file() == tmp_path / "worker_runs.jsonl"
    monkeypatch.delenv("MBOS_TELEMETRY_DIR")
    assert uv.telemetry_file().parts[-3:] == ("var", "telemetry", "worker_runs.jsonl")


def test_page_on_the_live_ui_is_read_only_and_host_checked(ui, tmp_path):
    fixture(tmp_path)
    ui.telemetry_dir = str(tmp_path)
    s, _, body = req(ui, "GET", "/usage")
    assert s == 200 and "Usage and agents" in body and "Claude Code estimate, not a bill" in body
    assert "<form" not in body.split("<main>")[1]
    assert req(ui, "GET", "/usage", host="evil.example")[0] == 403
    ui.telemetry_dir = None
