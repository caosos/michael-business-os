"""tools/reload_ui.sh safety (A-54): every test runs in a TEMP repo with PATH-shimmed tmux/curl, so nothing here can touch the live :8766.
Proves: a failed/incomplete export or backup aborts BEFORE any stop/remove; a wrong artifact or a page without the expected behaviour rolls back;
the success path swaps exactly the artifact and records its identity."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "reload_ui.sh"
GOOD_PAGES = {"market": "Michael's Marketplace name='cat' name='row1' name='row4' name='condition' name='any' Save this search Gallery rows",
              "market_validation": "<div id='filter-errors'>Radius must not be negative</div>", "mission": "Weekly mission", "queue": "Operator queue"}


def sh(cwd, *a, env=None):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True, check=True, env=env)


def write_shims(shims: Path, pages: Path, log: Path):
    shims.mkdir()
    (shims / "tmux").write_text(f'#!/bin/sh\necho "tmux $*" >> {log}\ncase "$1" in has-session) exit 0;; esac\nexit 0\n')
    (shims / "curl").write_text(f'''#!/bin/sh
echo "curl $*" >> {log}
url=""; for a in "$@"; do url="$a"; done
case "$*" in *redirect_url*) cat {pages}/root_redirect; exit 0;; esac
case "$url" in
  */market?go=1*) f=market_validation;; */market) f=market;; */mission) f=mission;; */queue) f=queue;; *) f=other;;
esac
n=$(grep -c '^tmux new-session' {log})
if [ "$n" -ge 2 ] && [ -f {pages}/after_rollback_code ]; then   # the rollback restart has happened: serve what the test configured
  case "$*" in *http_code*) cat {pages}/after_rollback_code; exit 0;; esac
  cat {pages}/after_rollback_body 2>/dev/null; exit 0
fi
case "$*" in *http_code*) echo 200; exit 0;; esac
cat {pages}/$f 2>/dev/null; exit 0
''')
    for f in shims.iterdir():
        f.chmod(f.stat().st_mode | stat.S_IEXEC)


def commit_artifact(origin_work: Path, files: dict, msg: str) -> str:
    for rel in ("operator_ui", "comms_spec"):
        shutil.rmtree(origin_work / rel, ignore_errors=True)
    for rel, text in files.items():
        p = origin_work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    sh(origin_work, "add", "-A")
    sh(origin_work, "commit", "-qm", msg)
    sh(origin_work, "push", "-q", "origin", "HEAD:research/agent-06-communications")
    return sh(origin_work, "rev-parse", "--short", "HEAD").stdout.strip()


GOOD_FILES = {"operator_ui/server.py": "NEW server\n", "operator_ui/market_view.py": "NEW view\n", "operator_ui/market_search.py": "NEW search\n", "comms_spec/spec.json": "{}\n"}


@pytest.fixture
def env(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = tmp_path / "authoring"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    (work / "README").write_text("x")
    sh(work, "add", "-A"); sh(work, "commit", "-qm", "seed")
    root = tmp_path / "root"
    subprocess.run(["git", "clone", "-q", str(origin), str(root)], check=True, capture_output=True)
    (root / "tools").mkdir()
    shutil.copy(SCRIPT, root / "tools" / "reload_ui.sh")
    live = root / "var/lanes/agent-06"
    (live / "operator_ui").mkdir(parents=True); (live / "comms_spec").mkdir()
    (live / "operator_ui/server.py").write_text("OLD server\n"); (live / "comms_spec/spec.json").write_text("{}\n")
    for f in ("dev.env", "owner.env", "ui.pin"):
        (root / "var" / f).write_text("x\n")
    pages, log, shims = tmp_path / "pages", tmp_path / "calls.log", tmp_path / "shims"
    pages.mkdir(); log.write_text("")
    for k, v in GOOD_PAGES.items():
        (pages / k).write_text(v)
    (pages / "root_redirect").write_text("303 http://127.0.0.1:8766/market")
    write_shims(shims, pages, log)

    class E:
        pass
    e = E(); e.root, e.live, e.pages, e.log, e.work, e.tmp = root, live, pages, log, work, tmp_path
    e.good_sha = commit_artifact(work, GOOD_FILES, "good artifact")
    e.run = lambda *args, extra=None: subprocess.run(["bash", str(root / "tools/reload_ui.sh"), *args], cwd=root, capture_output=True, text=True,
                                                    env={**os.environ, "PATH": f"{shims}:{os.environ['PATH']}", "MBOS_RELOAD_SLEEP_STOP": "0", "MBOS_RELOAD_SLEEP_START": "0", **(extra or {})})
    e.calls = lambda: log.read_text().splitlines()
    e.live_snapshot = lambda: {str(p.relative_to(live)): p.read_text() for p in sorted(live.rglob("*")) if p.is_file()}
    return e


def test_success_swaps_exactly_the_artifact_records_identity_and_keeps_a_backup(env):
    before = env.live_snapshot()
    r = env.run(env.good_sha)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (env.live / "operator_ui/server.py").read_text() == "NEW server\n"
    assert f"sha={env.good_sha}" in (env.live / "ARTIFACT").read_text() and "tree_sha256=" in (env.live / "ARTIFACT").read_text()
    kill = [i for i, c in enumerate(env.calls()) if c.startswith("tmux kill-session")]
    new = [i for i, c in enumerate(env.calls()) if c.startswith("tmux new-session")]
    assert kill and new and kill[0] < new[0]                                  # stopped, then started
    backups = list((env.root / "var/lanes").glob("agent-06.prev-*"))
    assert len(backups) == 1 and (backups[0] / "operator_ui/server.py").read_text() == before["operator_ui/server.py"]


def test_failed_backup_aborts_before_any_stop_or_removal(env):
    (env.root / "var/lanes").chmod(0o555)                                      # the backup copy cannot be created; the export (var/reload) still works
    try:
        before = env.live_snapshot()
        r = env.run(env.good_sha)
        assert r.returncode == 2 and "backup copy" in r.stdout
        assert not [c for c in env.calls() if c.startswith("tmux")]            # nothing stopped, nothing started
        assert env.live_snapshot() == before                                   # live files untouched
    finally:
        (env.root / "var/lanes").chmod(0o755)


def test_failed_export_aborts_before_any_stop_or_removal(env):
    before = env.live_snapshot()
    r = env.run("deadbeef")                                                    # unknown commit
    assert r.returncode == 2 and "unknown commit" in r.stdout
    assert not [c for c in env.calls() if c.startswith("tmux")] and env.live_snapshot() == before


def test_incomplete_export_aborts_before_any_stop_or_removal(env):
    sha = commit_artifact(env.work, {"operator_ui/server.py": "partial\n", "comms_spec/spec.json": "{}\n"}, "incomplete: no market_view.py")
    before = env.live_snapshot()
    r = env.run(sha)
    assert r.returncode == 2 and "lacks operator_ui/market_view.py" in r.stdout
    assert not [c for c in env.calls() if c.startswith("tmux")] and env.live_snapshot() == before


def test_commit_not_on_the_lane_branch_is_refused(env):
    sh(env.work, "checkout", "-q", "-b", "elsewhere")
    (env.work / "operator_ui").mkdir(exist_ok=True)
    (env.work / "operator_ui/x.py").write_text("x")
    sh(env.work, "add", "-A"); sh(env.work, "commit", "-qm", "off-lane")
    sha = sh(env.work, "rev-parse", "--short", "HEAD").stdout.strip()
    sh(env.work, "push", "-q", "origin", "HEAD:refs/heads/elsewhere")
    r = env.run(sha)
    assert r.returncode == 2 and "is not on origin/research/agent-06-communications" in r.stdout
    assert not [c for c in env.calls() if c.startswith("tmux")]


def test_http_200_without_the_expected_behaviour_rolls_back(env):
    (env.pages / "market").write_text("<html>Operator UI</html>")             # 200, but the old page: no marker
    before = env.live_snapshot()
    r = env.run(env.good_sha)
    assert r.returncode == 1 and "ROLLBACK" in r.stdout and "missing the marker" in r.stdout
    assert env.live_snapshot() == before                                       # the old UI is restored byte for byte
    assert len([c for c in env.calls() if c.startswith("tmux kill-session")]) == 2     # stop, then the rollback restart
    assert list((env.root / "var/lanes").glob("agent-06.prev-*"))              # the backup is kept


def test_a_fictional_item_on_a_demo_isolation_route_rolls_back(env):
    (env.pages / "queue").write_text("Needs your decision: 55 inch LED TV")
    r = env.run(env.good_sha)
    assert r.returncode == 1 and "fictional" in r.stdout and "ROLLBACK" in r.stdout


def test_wrong_files_on_disk_roll_back(env):
    # something changes the served files between the swap and the check (e.g. a wrong or concurrent write): the identity check must catch it
    shim = env.tmp / "shims" / "tmux"
    shim.write_text(f'''#!/bin/sh
echo "tmux $*" >> {env.log}
case "$1" in new-session) [ -f {env.live}/ARTIFACT ] && echo tampered >> {env.live}/operator_ui/server.py;; has-session) exit 0;; esac
exit 0
''')
    shim.chmod(0o755)
    r = env.run(env.good_sha)
    assert r.returncode == 1 and "the files on disk are not the artifact" in r.stdout and "ROLLBACK" in r.stdout
    assert (env.live / "operator_ui/server.py").read_text() == "OLD server\n"          # restored from the verified backup


def test_verify_only_never_stops_or_changes_anything(env):
    before = env.live_snapshot()
    assert env.run("--verify-only", "8767").returncode == 0
    assert env.live_snapshot() == before and not [c for c in env.calls() if c.startswith("tmux")]
    (env.pages / "market").write_text("old page")
    r = env.run("--verify-only", "8767")
    assert r.returncode == 1 and "missing the marker" in r.stdout and not [c for c in env.calls() if c.startswith("tmux")]


def test_rollback_that_only_gets_http_500_is_reported_as_failed_not_recovered(env):
    (env.pages / "market").write_text("<html>new UI is broken</html>")             # the new UI fails the semantic check -> rollback
    (env.pages / "after_rollback_code").write_text("500")                           # ...and the 'restored' UI answers HTTP 500
    (env.pages / "after_rollback_body").write_text("Internal Server Error")
    r = env.run(env.good_sha)
    assert r.returncode == 3 and "ROLLBACK FAILED OR UNVERIFIED" in r.stdout and "rollback done and verified" not in r.stdout
    assert (env.live / "operator_ui/server.py").read_text() == "OLD server\n"          # the files were still restored, the backup is kept and named
    assert list((env.root / "var/lanes").glob("agent-06.prev-*"))


def test_rollback_to_a_200_page_that_lost_the_baseline_marker_is_not_recovery(env):
    (env.pages / "market").write_text("Michael's Marketplace but missing the F-57 fields")          # baseline had the marker; the new UI fails the checks
    (env.pages / "after_rollback_code").write_text("200")
    (env.pages / "after_rollback_body").write_text("<html>some other page</html>")                  # 200, but not the old UI's healthy page
    r = env.run(env.good_sha)
    assert r.returncode == 3 and "ROLLBACK FAILED OR UNVERIFIED" in r.stdout


def test_a_failing_rm_after_the_stop_triggers_recovery_not_a_dead_ui(env):
    real_rm = shutil.which("rm")
    shim = env.tmp / "shims" / "rm"                                                 # the post-stop removal of the live files fails; everything else works
    shim.write_text(f'''#!/bin/sh
case "$*" in *agent-06/operator_ui*) echo "rm: injected failure" >&2; exit 1;; esac
exec {real_rm} "$@"
''')
    shim.chmod(0o755)
    before = env.live_snapshot()
    r = env.run(env.good_sha)
    assert r.returncode == 1 and "ROLLBACK to" in r.stdout and "a command failed after the UI was stopped" in r.stdout and "rollback done and verified" in r.stdout
    assert env.live_snapshot() == before                                            # restored byte for byte
    calls = env.calls()
    assert len([c for c in calls if c.startswith("tmux kill-session")]) == 2 and len([c for c in calls if c.startswith("tmux new-session")]) == 1   # stop, then ONE restart (the rollback's); the new UI never started


def test_a_rollback_that_is_verified_requires_the_baseline_answer(env):
    (env.pages / "market").write_text("<html>new UI is broken</html>")
    (env.pages / "after_rollback_code").write_text("200")
    (env.pages / "after_rollback_body").write_text("Michael's Marketplace (old UI healthy)")
    r = env.run(env.good_sha)
    assert r.returncode == 1 and "rollback done and verified" in r.stdout            # the same healthy answer as before: recovery accepted
