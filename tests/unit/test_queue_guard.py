"""A-57: the queue-merge guard rejects the concrete 9435d68 stale-side merge and accepts attributed reopen/cancel/edit."""
import subprocess
import unittest
from pathlib import Path

from tools.queue_guard import check

ROOT = Path(__file__).resolve().parents[2]
Q = "docs/status/READY_QUEUE.md"
HEAD = "| ID | Pri | Task | Deps | Status | Agent | Acceptance |\n"


def row(tid, status, deps="none", agent="06"):
    return f"| {tid} | P1 | title of {tid} | {deps} | {status} | {agent} | proof |\n"


def show(rev):
    r = subprocess.run(["git", "show", f"{rev}:{Q}"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def mark(task, action, **kw):
    return {"task": task, "actor": "agent-01", "reason": "owner asked", "message": "ARYA-1", "action": action, **kw}


class QueueGuard(unittest.TestCase):
    def test_9435d68_stale_side_merge_is_rejected(self):
        parents, merged = [show("f5a844a"), show("7a54f65")], show("9435d68")
        if not all(parents) or not merged:
            self.skipTest("the 9435d68 objects are not in this clone")
        problems = check(merged, parents)
        self.assertTrue(problems, "the stale-side merge must be rejected")
        text = " ".join(problems)
        self.assertIn("F-60", text)                                # F-60 reverted/dropped
        self.assertTrue(any("F-61" in p and "dropped" in p for p in problems) or "F-61" in text)

    def test_dropped_row_rejected(self):
        self.assertTrue(check(HEAD + row("F-1", "READY"), [HEAD + row("F-1", "READY") + row("F-2", "READY")]))

    def test_done_reverted_rejected_f60_stays_done(self):
        p = check(HEAD + row("F-60", "READY"), [HEAD + row("F-60", "DONE")])
        self.assertEqual(len(p), 1)
        self.assertIn("F-60", p[0])
        self.assertEqual(check(HEAD + row("F-60", "DONE"), [HEAD + row("F-60", "DONE")]), [])

    def test_lost_deps_and_owner_rejected(self):
        p = check(HEAD + row("F-9", "READY", "none", "none"), [HEAD + row("F-9", "READY", "F-8", "06")])
        self.assertEqual(len(p), 2)

    def test_normal_progress_passes(self):
        old = HEAD + row("F-1", "READY") + row("F-2", "READY", "F-1")
        new = HEAD + row("F-1", "DONE") + row("F-2", "READY", "F-1") + row("F-3", "READY")
        self.assertEqual(check(new, [old]), [])

    def test_attributed_reopen_cancel_edit_pass(self):
        self.assertEqual(check(HEAD + row("F-1", "READY"), [HEAD + row("F-1", "DONE")], [mark("F-1", "reopen")]), [])
        self.assertEqual(check(HEAD, [HEAD + row("F-1", "READY")], [mark("F-1", "cancel")]), [])
        self.assertEqual(check(HEAD + row("F-1", "READY", "none"), [HEAD + row("F-1", "READY", "F-0")], [mark("F-1", "edit")]), [])

    def test_unattributed_or_wrong_marker_is_ignored(self):
        old, new = [HEAD + row("F-1", "DONE")], HEAD + row("F-1", "READY")
        self.assertTrue(check(new, old, [mark("F-1", "reopen", actor="")]))        # missing actor
        self.assertTrue(check(new, old, [mark("F-2", "reopen")]))                   # other task
        self.assertTrue(check(new, old, [mark("F-1", "edit")]))                     # wrong action


if __name__ == "__main__":
    unittest.main()
