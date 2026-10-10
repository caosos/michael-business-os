"""Git plumbing for automatic pickup: read the liaison inbox, find ACKs, publish ACK/receipt files from a side worktree, publish the heartbeat.

Every write goes only to `research/agent-01-coordinator` (docs files, fast-forward) or `status/agent-01-pickup` (one heartbeat file). No force-push, no gh,
no tokens: it uses the same git remote the other tools use.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
INBOX_REF = os.environ.get("MBOS_INBOX_REF", "origin/liaison/aria-to-agent-01")
COORD = os.environ.get("MBOS_COORD_BRANCH", "research/agent-01-coordinator")
SIDE_BRANCH = "research/agent-01-pickup"
STATUS_BRANCH = "status/agent-01-pickup"
SIDE = Path(os.environ.get("MBOS_PICKUP_WORKTREE", str(Path.home() / "business-os-worktrees" / "inbox-side")))
IDENT = ["-c", "user.name=Agent 01 Pickup", "-c", "user.email=michaelos+agent-01-pickup@users.noreply.github.com"]


def git(*args: str, cwd: Optional[Path] = None, inp: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, input=inp, timeout=120)


def fetch() -> bool:
    return git("fetch", "-q", "origin").returncode == 0


def list_md(ref: str, folder: str) -> list[str]:
    r = git("ls-tree", "--name-only", ref, folder.rstrip("/") + "/")
    return sorted(Path(x).stem for x in r.stdout.split() if x.endswith(".md")) if r.returncode == 0 else []


def inbox_ids() -> list[str]:
    return list_md(INBOX_REF, "docs/messages/inbox")


def acked_ids() -> set[str]:
    return set(list_md("origin/" + COORD, "docs/messages/acks"))


def read_message(mid: str) -> Optional[str]:
    r = git("show", f"{INBOX_REF}:docs/messages/inbox/{mid}.md")
    return r.stdout if r.returncode == 0 else None


def head(ref: str = "origin/" + COORD) -> str:
    return git("rev-parse", "--short", ref).stdout.strip()


def prepare_side() -> tuple[Optional[Path], str]:
    """The side worktree (never the interactive one) reset to the coordinator head. -> (path, '') or (None, reason)."""
    if not SIDE.exists():
        r = git("worktree", "add", "-q", "-B", SIDE_BRANCH, str(SIDE), "origin/" + COORD)
        return (SIDE, "") if r.returncode == 0 else (None, "cannot create side worktree: " + r.stderr.strip()[:160])
    if git("status", "--porcelain", cwd=SIDE).stdout.strip():
        return None, f"side worktree {SIDE} has uncommitted changes (inspect before the next run)"
    r = git("checkout", "-q", "-B", SIDE_BRANCH, "origin/" + COORD, cwd=SIDE)
    return (SIDE, "") if r.returncode == 0 else (None, "cannot reset side worktree: " + r.stderr.strip()[:160])


def commit_all(wt: Path, message: str) -> Optional[str]:
    git("add", "-A", "docs", cwd=wt)
    if not git("status", "--porcelain", cwd=wt).stdout.strip():
        return None
    r = git(*IDENT, "commit", "-q", "-m", message + "\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>", cwd=wt)
    return git("rev-parse", "--short", "HEAD", cwd=wt).stdout.strip() if r.returncode == 0 else None


def publish(wt: Path) -> tuple[bool, str]:
    """Fast-forward the coordinator branch with the side branch (one rebase retry if the coordinator moved). -> (ok, detail)."""
    resolved = False
    for _ in range(2):
        r = git("push", "-q", "origin", f"HEAD:{COORD}", cwd=wt)
        if r.returncode == 0:
            return True, git("rev-parse", "--short", "HEAD", cwd=wt).stdout.strip() + (" (same-line docs conflict resolved in favour of upstream)" if resolved else "")
        git("fetch", "-q", "origin", cwd=wt)
        rb = git(*IDENT, "rebase", "-q", "origin/" + COORD, cwd=wt)
        if rb.returncode != 0:
            git("rebase", "--abort", cwd=wt)
            # Docs-only changes (the caller's guard has passed): on a same-line conflict (typically the executor and the coordinator both edited one
            # READY_QUEUE row) the coordinator's upstream line wins; the executor's non-conflicting additions are kept. Recorded in the detail.
            rb = git(*IDENT, "rebase", "-q", "-X", "ours", "origin/" + COORD, cwd=wt)
            if rb.returncode != 0:
                git("rebase", "--abort", cwd=wt)
                return False, "push rejected and rebase failed even preferring upstream: " + (rb.stderr.strip() or rb.stdout.strip())[:200]
            resolved = True
    return False, "push rejected twice"


def changed_files(wt: Path) -> list[str]:
    """Files THIS run changed: committed since the fork point (merge-base with the coordinator branch, so commits others pushed meanwhile are not
    counted), plus uncommitted and untracked files."""
    base = git("merge-base", "HEAD", "origin/" + COORD, cwd=wt).stdout.strip() or "origin/" + COORD
    a = git("diff", "--name-only", base, cwd=wt).stdout.split()
    b = git("ls-files", "--others", "--exclude-standard", cwd=wt).stdout.split()
    return sorted(set(a + b))


def publish_heartbeat(json_text: str) -> tuple[bool, str]:
    """Commit the heartbeat file on `status/agent-01-pickup` without touching any checkout (hash-object, mktree, commit-tree, push)."""
    blob = git("hash-object", "-w", "--stdin", inp=json_text).stdout.strip()
    tree = git("mktree", inp=f"100644 blob {blob}\tPICKUP_HEALTH.json\n").stdout.strip()
    git("fetch", "-q", "origin", STATUS_BRANCH)
    parent = git("rev-parse", "-q", "--verify", "origin/" + STATUS_BRANCH).stdout.strip()
    args = ["commit-tree", tree, "-m", "pickup heartbeat"] + (["-p", parent] if parent else [])
    commit = git(*IDENT, *args).stdout.strip()
    if not commit:
        return False, "commit-tree failed"
    r = git("push", "-q", "origin", f"{commit}:refs/heads/{STATUS_BRANCH}")
    return (r.returncode == 0), (commit[:7] if r.returncode == 0 else r.stderr.strip()[:140])
