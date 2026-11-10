"""Invented personal records: state transitions, historical evidence and recovery."""

import io
import json
import sqlite3
import unittest
from contextlib import closing, redirect_stdout
from unittest.mock import patch

from test_knowledge import WorkspaceFixture
from knowledge.catalog import Catalog
from knowledge.cli import main
from knowledge.common import KnowledgeError
from knowledge.reflection import checkin, review, task
from knowledge.service import rebuild, search, sync


class ReflectionCase(WorkspaceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.clock = patch("knowledge.reflection.current_day", return_value="2026-01-11")
        self.clock.start()
        self.addCleanup(self.clock.stop)
        renderer_clock = patch("knowledge.personal_render.current_day", return_value="2026-01-11")
        renderer_clock.start()
        self.addCleanup(renderer_clock.stop)

    def state(self):
        catalog = Catalog(self.root)
        try:
            return catalog.personal_state()
        finally:
            catalog.close()

    def add(self, **kwargs):
        return task(self.root, "add", "交付虚构项目", day="2026-01-05", **kwargs)["id"]

    def test_old_catalog_is_upgraded_without_losing_sources(self):
        self.note()
        self.configure()
        sync(self.root)
        with closing(sqlite3.connect(self.root / ".knowledge/catalog.sqlite3")) as connection, connection:
            for table in ("checkins", "commitments", "commitment_events"):
                connection.execute("DROP TABLE " + table)
        rebuild(self.root)
        self.assertEqual(self.state(), {"checkins": [], "tasks": [], "events": []})
        catalog = Catalog(self.root)
        try:
            self.assertEqual(len(catalog.rows()), 1)
        finally:
            catalog.close()

    def test_daily_merge_deduplicates_and_replace_is_explicit(self):
        checkin(self.root, "2026-01-05", ["完成原型"], ["等待接口"], [])
        checkin(self.root, "2026-01-05", ["完成原型", "验证原型"], [], ["先测依赖"])
        self.assertEqual(self.state()["checkins"][0]["done"], ["完成原型", "验证原型"])
        checkin(self.root, "2026-01-05", ["更正：只完成草稿"], [], [], replace=True)
        self.assertEqual(self.state()["checkins"][0]["blocked"], [])
        page = (self.root / "Daily/2026-01-05.md").read_text(encoding="utf-8")
        self.assertIn("更正：只完成草稿", page)
        self.assertNotIn("完成原型", page)
        self.assertIn("2026-01-05", (self.root / "Timeline.md").read_text(encoding="utf-8"))

    def test_invalid_and_secret_entries_do_not_advance_state(self):
        for day in ("2026-1-5", "2026-02-30", "2026-01-12"):
            with self.assertRaises(KnowledgeError):
                checkin(self.root, day, ["结果"], [], [])
        with self.assertRaises(KnowledgeError):
            checkin(self.root, None, [], [], [])
        with self.assertRaises(KnowledgeError):
            checkin(self.root, None, ["sk-" + "a" * 35], [], [])
        with self.assertRaises(KnowledgeError):
            task(self.root, "add", "任务", source_id="nonexistent")
        self.assertEqual(self.state()["checkins"], [])
        self.assertEqual(self.state()["tasks"], [])

    def test_confirmation_is_idempotent_and_outcome_is_required(self):
        identifier = self.add(due="2026-01-07", expected="一个可运行原型")
        self.assertEqual(self.add(due="2026-01-07", expected="一个可运行原型"), identifier)
        self.assertEqual(len(self.state()["events"]), 1)
        with self.assertRaisesRegex(KnowledgeError, "different details"):
            self.add(due="2026-01-08", expected="一个可运行原型")
        with self.assertRaises(KnowledgeError):
            task(self.root, "finish", identifier, day="2026-01-06")
        task(self.root, "finish", identifier, day="2026-01-06", outcome="原型通过验收")
        current = task(self.root, "list")[0]
        self.assertEqual((current["status"], current["outcome"]), ("done", "原型通过验收"))
        self.assertEqual(review(self.root)["metrics"]["completed"], 1)

    def test_deferral_audit_and_historical_review_exclude_future_results(self):
        identifier = self.add(due="2026-01-06")
        for day, due in (("2026-01-06", "2026-01-08"), ("2026-01-08", "2026-01-10")):
            task(self.root, "defer", identifier, day=day, due=due, reason="依赖未准备好")
        task(self.root, "finish", identifier, day="2026-01-10", outcome="交付可用原型")
        task(self.root, "add", "后续计划", day="2026-01-11")
        historical = review(self.root, "2026-01-09")
        self.assertEqual(historical["metrics"]["completed"], 0)
        self.assertEqual(historical["metrics"]["open_commitments"], 1)
        finding = next(item for item in historical["findings"] if item["kind"] == "repeated_deferral")
        self.assertEqual(len(finding["evidence"]), 2)
        page = (self.root / "Tasks.md").read_text(encoding="utf-8")
        self.assertIn("原截止 2026-01-06", page)
        self.assertIn("交付可用原型", page)
        self.assertIn("#event-", (self.root / "Review.md").read_text(encoding="utf-8"))

    def test_weekly_view_uses_week_end_not_later_completion(self):
        identifier = task(self.root, "add", "跨周任务", day="2026-01-02", due="2026-01-03")["id"]
        task(self.root, "finish", identifier, day="2026-01-06", outcome="完成交付")
        old = (self.root / "Reviews/2026-W01.md").read_text(encoding="utf-8")
        self.assertIn("截至 2026-01-04", old)
        self.assertIn("| 已记录完成的承诺 | 0 |", old)
        self.assertIn("状态仍为未完成", old)
        self.assertEqual(review(self.root)["metrics"]["completed"], 1)

    def test_cancel_reopen_and_date_order_prevent_false_overdue(self):
        identifier = self.add(due="2026-01-06")
        with self.assertRaises(KnowledgeError):
            task(self.root, "defer", identifier, day="2026-01-05", due="2026-01-06", reason="原因")
        task(self.root, "cancel", identifier, day="2026-01-07", reason="目标已经改变")
        self.assertEqual(review(self.root)["metrics"]["overdue"], 0)
        with self.assertRaises(KnowledgeError):
            task(self.root, "finish", identifier, day="2026-01-08", outcome="结果")
        task(self.root, "reopen", identifier, day="2026-01-08", reason="恢复原目标")
        self.assertEqual(review(self.root)["metrics"]["overdue"], 1)
        with self.assertRaises(KnowledgeError):
            task(self.root, "finish", identifier, day="2026-01-06", outcome="结果")

    def test_blocker_rules_require_distinct_days_and_missing_days_are_unknown(self):
        checkin(self.root, "2026-01-05", ["完成小步"], ["等待接口", "等待接口"], [])
        checkin(self.root, "2026-01-06", [], ["等待接口"], [])
        self.assertFalse(review(self.root)["findings"])
        checkin(self.root, "2026-01-07", [], ["等待接口"], [])
        result = review(self.root)
        self.assertEqual(result["metrics"]["unobserved_days"], 4)
        self.assertEqual(result["wins"], [{"day": "2026-01-05", "text": "完成小步"}])
        self.assertEqual(result["findings"][0]["evidence"],
                         ["checkin:2026-01-05", "checkin:2026-01-06", "checkin:2026-01-07"])

    def test_sync_preserves_personal_records_notes_and_does_not_create_tasks(self):
        self.note(body="# 计划\n\n明天做一个虚构项目。")
        self.configure()
        note = self.root / "Notes/personal.md"
        note.write_text("手写内容", encoding="utf-8")
        checkin(self.root, "2026-01-05", ["完成草稿"], [], [])
        identifier = self.add()
        before = self.state()
        sync(self.root)
        rebuild(self.root)
        self.assertEqual(self.state(), before)
        self.assertEqual(len(self.state()["tasks"]), 1)
        self.assertEqual(note.read_text(encoding="utf-8"), "手写内容")
        self.assertIn(identifier, (self.root / "Tasks.md").read_text(encoding="utf-8"))

    def test_render_failure_keeps_saved_fact_rebuild_recovers_without_model(self):
        with patch("knowledge.render.commit", side_effect=KnowledgeError("simulated interruption")):
            with self.assertRaises(KnowledgeError):
                checkin(self.root, "2026-01-05", ["完成草稿"], [], [])
        self.assertEqual(self.state()["checkins"][0]["done"], ["完成草稿"])
        with patch("knowledge.service.summarize") as model:
            rebuild(self.root)
            model.assert_not_called()
        self.assertIn("完成草稿", (self.root / "Daily/2026-01-05.md").read_text(encoding="utf-8"))

    def test_cli_records_and_reviews_without_calling_provider(self):
        output = io.StringIO()
        with patch("knowledge.service.summarize") as model, redirect_stdout(output):
            self.assertEqual(main(["checkin", "--workspace", str(self.root), "--done", "完成演示"]), 0)
            model.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["date"], "2026-01-11")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["task", "--workspace", str(self.root), "add", "下一步", "--expected", "可验收结果"]), 0)
            self.assertEqual(main(["review", "--workspace", str(self.root), "--as-of", "2026-01-11"]), 0)

    def test_search_includes_self_reports_and_actual_task_results(self):
        checkin(self.root, "2026-01-05", [], ["等待虚构接口"], [])
        identifier = self.add(expected="可运行原型")
        task(self.root, "finish", identifier, outcome="虚构验收通过")
        self.assertEqual(search(self.root, "等待虚构接口")[0]["file"], "Daily/2026-01-05.md#checkin")
        self.assertEqual(search(self.root, "虚构验收通过")[0]["file"], f"Tasks.md#task-{identifier}")
        self.assertEqual(search(self.root, "不存在的记录"), [])
