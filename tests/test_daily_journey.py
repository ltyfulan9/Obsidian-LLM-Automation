"""Daily user journeys use invented data and isolate provider/network access."""

import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from knowledge.catalog import Catalog
from knowledge.cli import main


class DailyJourneyCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="knowledge-daily-journey-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "虚构 知识库"
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.model = stack.enter_context(patch("knowledge.summarize.invoke_cli", side_effect=AssertionError("No model calls in this journey")))
        self.network = stack.enter_context(patch("urllib.request.urlopen", side_effect=AssertionError("No source fetching in this journey")))
        stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("No network in this journey")))
        self.remote = stack.enter_context(patch("knowledge.publish.private_target", side_effect=AssertionError("No implicit publication")))
        self.demo = self.json_command("demo")

    def invoke(self, command, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main([command, "--workspace", str(self.root), *arguments])
        return code, output.getvalue(), errors.getvalue()

    def json_command(self, command, *arguments):
        code, output, errors = self.invoke(command, *arguments)
        self.assertEqual(code, 0, errors)
        return json.loads(output)

    def personal_state(self):
        catalog = Catalog(self.root)
        try:
            return catalog.personal_state()
        finally:
            catalog.close()

    def test_find_source_finish_commitment_and_review_actual_result(self):
        code, text, errors = self.invoke("search", "园艺", "--kind", "markdown", "--format", "text")
        self.assertEqual(code, 0, errors)
        self.assertIn("本地摘录", text)
        self.assertIn("demo-notes", text)
        self.assertIn("园艺", text)
        self.assertIn("Sources/", text)

        identifier = self.demo["task_id"]
        opened = self.json_command("task", "list", "--status", "open")
        self.assertEqual([task["id"] for task in opened], [identifier])
        previous_checkins = self.personal_state()["checkins"]
        outcome = "虚构验收：观察表已包含三个栏目，并核对一份样本"
        self.json_command("task", "finish", identifier, "--outcome", outcome)
        self.assertEqual(self.personal_state()["checkins"], previous_checkins,
                         "Finishing a task must not fabricate a separate daily self-report")

        review = self.json_command("review")
        completed = next(task for task in review["completed_tasks"] if task["id"] == identifier)
        self.assertEqual(completed["outcome"], outcome)
        self.assertTrue(completed["expected"])
        self.assertTrue(completed["event"])
        page = (self.root / "Review.md").read_text(encoding="utf-8")
        achievements = page.split("## 做成了什么", 1)[1].split("\n## ", 1)[0]
        self.assertIn(outcome, achievements)
        self.assertIn(f"Tasks.md#event-{completed['event']}", achievements)
        self.assertIn(outcome, (self.root / "Tasks.md").read_text(encoding="utf-8"))
        self.assertEqual(self.json_command("task", "list", "--status", "open"), [])
        done = self.json_command("task", "list", "--status", "done")
        self.assertEqual([task["id"] for task in done], [identifier])
        self.assertEqual(done[0]["outcome"], outcome)
        code, text, errors = self.invoke("task", "list", "--status", "done", "--format", "text")
        self.assertEqual(code, 0, errors)
        self.assertIn(identifier, text)
        self.model.assert_not_called()
        self.network.assert_not_called()
        self.remote.assert_not_called()

    def test_overdue_list_excludes_cancelled_and_future_due_commitments(self):
        created = (date.today() - timedelta(days=3)).isoformat()
        past_due = (date.today() - timedelta(days=1)).isoformat()
        active = self.json_command("task", "add", "虚构逾期观察", "--date", created, "--due", past_due)["id"]
        cancelled = self.json_command("task", "add", "虚构取消观察", "--date", created, "--due", past_due)["id"]
        self.json_command("task", "cancel", cancelled, "--reason", "虚构目标已经改变")
        overdue = self.json_command("task", "list", "--overdue")
        self.assertEqual([task["id"] for task in overdue], [active])
        self.assertNotIn(self.demo["task_id"], [task["id"] for task in overdue])
        self.assertEqual([task["id"] for task in self.json_command("task", "list", "--status", "cancelled")], [cancelled])
        self.assertEqual(len(self.json_command("task", "list")), 3, "Default list remains JSON containing all statuses")

    def test_search_filters_dates_and_record_types_without_semantic_claims(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        for kind in ("markdown", "export", "task", "checkin"):
            with self.subTest(kind=kind):
                hits = self.json_command("search", "虚构", "--kind", kind, "--since", today, "--until", today)
                self.assertTrue(hits)
                self.assertTrue(all(hit["kind"] == kind and hit["date"] == today for hit in hits))
                self.assertTrue(all(hit["snippet"] for hit in hits))
        markdown = self.json_command("search", "园艺", "--kind", "markdown")
        self.assertEqual(markdown[0]["method"], "extract")
        self.assertEqual(markdown[0]["source"], "demo-notes")
        self.assertEqual(self.json_command("search", "虚构", "--until", yesterday), [])
        self.assertEqual(self.json_command("search", "完全不存在的同义词"), [])

    def test_invalid_search_window_reports_error_instead_of_silently_ignoring_it(self):
        code, _, errors = self.invoke("search", "虚构", "--since", "2026-01-03", "--until", "2026-01-02")
        self.assertEqual(code, 1)
        self.assertTrue(errors)

    def test_search_old_activity_window_never_matches_later_completion(self):
        created = (date.today() - timedelta(days=4)).isoformat()
        cutoff = (date.today() - timedelta(days=2)).isoformat()
        finished = (date.today() - timedelta(days=1)).isoformat()
        title = "虚构旧窗口观察任务"
        outcome = "虚构红色观测样本已验收"
        identifier = self.json_command("task", "add", title, "--date", created, "--expected", "一份可核对样本")["id"]
        self.json_command("task", "finish", identifier, "--date", finished, "--outcome", outcome)
        old_hits = self.json_command("search", title, "--kind", "task", "--until", cutoff)
        self.assertEqual(len(old_hits), 1)
        self.assertEqual(old_hits[0]["date"], created)
        self.assertNotIn(outcome, old_hits[0]["snippet"])
        self.assertEqual(self.json_command("search", outcome, "--kind", "task", "--until", cutoff), [])
        new_hits = self.json_command("search", outcome, "--kind", "task", "--since", finished)
        self.assertEqual(len(new_hits), 1)
        self.assertEqual(new_hits[0]["date"], finished)
        self.assertIn(identifier, new_hits[0]["file"])

    def test_list_only_options_do_not_silently_create_a_task(self):
        before = self.personal_state()
        for arguments in (("--status", "open"), ("--overdue",), ("--format", "text")):
            with self.subTest(arguments=arguments):
                code, _, errors = self.invoke("task", "add", "虚构误用选项不应创建", *arguments)
                self.assertEqual(code, 1)
                self.assertTrue(errors)
                self.assertEqual(self.personal_state(), before)


if __name__ == "__main__":
    unittest.main()
