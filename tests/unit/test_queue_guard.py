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


class A59(unittest.TestCase):
    def test_partial_dependency_drop_rejected(self):
        p = check(HEAD + row("F-9", "READY", "A-54, A-55"), [HEAD + row("F-9", "READY", "A-54, A-55, F-138")])
        self.assertEqual(len(p), 1)
        self.assertIn("F-138", p[0])
        self.assertEqual(check(HEAD + row("F-9", "READY", "A-54, A-55", "06"), [HEAD + row("F-9", "READY", "A-54,A-55", "06")]), [])    # formatting only
        self.assertEqual(check(HEAD + row("F-9", "READY", "none"), [HEAD + row("F-9", "READY", "none")]), [])

    def test_owner_replacement_rejected_but_refinement_passes(self):
        self.assertEqual(len(check(HEAD + row("F-9", "READY", agent="01"), [HEAD + row("F-9", "READY", agent="06")])), 1)
        self.assertEqual(check(HEAD + row("F-9", "READY", agent="01 engineering"), [HEAD + row("F-9", "READY", agent="01")]), [])
        self.assertEqual(check(HEAD + row("F-9", "READY", agent="01"), [HEAD + row("F-9", "READY", agent="06")], [mark("F-9", "edit")]), [])

    def test_done_history_must_be_merged_not_replaced(self):
        from tools.queue_guard import done_line_problems
        old = "Done: F-137 @ d537b27 · F-136 @ 48d27b9 · F-61 @ e54e27a · F-60 @ 64b152b\n"
        self.assertEqual(done_line_problems(old, "Done: F-138 @ 22bb3ab · " + old[6:]), [])
        bad = done_line_problems(old, "Done: F-61 @ e54e27a; F-138 @ 22bb3ab\n")
        self.assertTrue(bad and "F-137" in bad[0] and "F-60" in bad[0])
        self.assertEqual(done_line_problems(None, "Done: F-1 @ a\n"), [])

    def test_22bb3ab_regression_replay(self):
        from tools.queue_guard import done_line_problems
        st = lambda rev: subprocess.run(["git", "show", f"{rev}:docs/status/AGENT_STATUS.md"], cwd=ROOT, capture_output=True, text=True).stdout
        eda, bad = st("eda3eee"), st("22bb3ab")
        if not eda or not bad:
            self.skipTest("lane 06 commits not in this clone")
        problems = done_line_problems(eda, bad)
        self.assertTrue(problems and "F-137" in problems[0] and "F-59" in problems[0], problems)
        self.assertEqual(done_line_problems(eda, eda), [])
