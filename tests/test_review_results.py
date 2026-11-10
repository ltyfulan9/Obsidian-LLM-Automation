"""Confirmed outcomes are first-class review evidence, without duplicate check-ins."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from test_knowledge import WorkspaceFixture
from knowledge.catalog import Catalog
from knowledge.cli import main
from knowledge.reflection import review, task


class ReviewResultCase(WorkspaceFixture, unittest.TestCase):
    def test_finished_task_is_a_review_accomplishment_without_checkin(self):
        identifier = task(self.root, "add", "Invented observation table", day="2026-01-05", expected="Three columns")["id"]
        task(self.root, "finish", identifier, day="2026-01-06", outcome="Three columns verified")
        result = review(self.root, "2026-01-07")
        self.assertEqual(result["wins"], [])
        self.assertEqual(len(result["completed_tasks"]), 1)
        completed = result["completed_tasks"][0]
        self.assertEqual(completed["outcome"], "Three columns verified")
        self.assertEqual(completed["expected"], "Three columns")
        # The historical weekly projection keeps its completion evidence.
        page = (self.root / "Reviews/2026-W02.md").read_text(encoding="utf-8")
        self.assertIn("Three columns verified", page)
        self.assertIn(f"Tasks.md#event-{completed['event']}", page)

    def test_historical_review_does_not_include_future_outcome(self):
        identifier = task(self.root, "add", "Invented experiment", day="2026-01-05")["id"]
        task(self.root, "finish", identifier, day="2026-01-07", outcome="Invented future result")
        self.assertEqual(review(self.root, "2026-01-06")["completed_tasks"], [])

    def test_reopening_keeps_history_but_removes_current_completion(self):
        identifier = task(self.root, "add", "Invented experiment", day="2026-01-05")["id"]
        task(self.root, "finish", identifier, day="2026-01-06", outcome="First result")
        task(self.root, "reopen", identifier, day="2026-01-07", reason="More verification needed")
        self.assertEqual(review(self.root, "2026-01-07")["completed_tasks"], [])
        self.assertEqual(review(self.root, "2026-01-06")["completed_tasks"][0]["outcome"], "First result")

    def test_list_filters_are_rejected_before_task_creation(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["task", "--workspace", str(self.root), "add", "Unintended task", "--overdue"]), 1)
        catalog = Catalog(self.root)
        try:
            self.assertEqual(catalog.personal_state()["tasks"], [])
        finally:
            catalog.close()
