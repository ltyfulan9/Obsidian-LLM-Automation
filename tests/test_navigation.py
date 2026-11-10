"""Synthetic navigation: daily entry, confirmed follow-ups and visible provenance."""

import unittest
from unittest.mock import patch

from knowledge.common import slug
from knowledge.render import projections


class NavigationCase(unittest.TestCase):
    def setUp(self):
        self.config = {"sources": [], "engine": {"name": "extract"}, "timezone": "UTC"}
        clock = patch("knowledge.reflection.current_day", return_value="2026-01-11")
        clock.start()
        self.addCleanup(clock.stop)

    def source(self, identifier="fixture", method="extract", available=True, day="2026-01-10"):
        return {"document": {"id": identifier, "source": "invented", "origin": identifier + ".md",
                             "kind": "markdown", "day": day},
                "summary": {"title": "虚构资料", "summary": "虚构摘要", "topics": ["虚构主题"],
                            "key_points": [], "decisions": [], "questions": ["AI 提议的一个任务"], "method": method},
                "available": available}

    def test_empty_workspace_has_specific_next_steps_without_dead_today_link(self):
        home = projections([], self.config)["Home.md"]
        self.assertIn("knowledge source markdown", home)
        self.assertIn("knowledge sync", home)
        self.assertIn("Notes/README.md", home)
        self.assertNotIn("(Daily/2026-01-11.md)", home)
        self.assertIn("不代表后台任务已经启用", home)

    def test_configured_but_unsynced_workspace_directs_user_to_sync(self):
        self.config["sources"] = [{"name": "fictional-notes", "kind": "markdown"}]
        home = projections([], self.config)["Home.md"]
        self.assertIn("已配置 1 个来源，尚无已整理资料", home)
        self.assertIn("knowledge sync", home)
        self.assertNotIn("knowledge source markdown", home)

    def test_dates_include_personal_records_and_today_has_valid_entry(self):
        personal = {"checkins": [{"day": "2026-01-11", "done": ["完成虚构验收"], "blocked": [], "lessons": []}]}
        files = projections([self.source()], self.config, personal)
        home = files["Home.md"]
        self.assertIn("**1** 份资料", home)
        self.assertIn("**2** 个有记录日期（含资料、回填与承诺变更）", home)
        self.assertIn("[打开今天的记录](Daily/2026-01-11.md)", home)
        self.assertIn("每日回填：已记录", home)
        self.assertIn("Daily/2026-01-11.md", files)

    def test_home_only_surfaces_confirmed_open_tasks_and_replays_as_of_today(self):
        personal = {"tasks": [
            {"id": "late", "title": "虚构逾期承诺", "created": "2026-01-01", "expected": "结果"},
            {"id": "closed", "title": "虚构已完成承诺", "created": "2026-01-01", "expected": "结果"},
            {"id": "future", "title": "虚构未来承诺", "created": "2026-01-12", "expected": "结果"},
        ], "events": [
            {"seq": 1, "task_id": "late", "day": "2026-01-01", "kind": "add", "due": "2026-01-10"},
            {"seq": 2, "task_id": "closed", "day": "2026-01-01", "kind": "add", "due": "2026-01-10"},
            {"seq": 3, "task_id": "closed", "day": "2026-01-10", "kind": "finish", "outcome": "通过验收"},
            {"seq": 4, "task_id": "future", "day": "2026-01-12", "kind": "add", "due": None},
        ]}
        home = projections([self.source()], self.config, personal)["Home.md"]
        self.assertIn("[虚构逾期承诺](Tasks.md#task-late)", home)
        self.assertIn("仍打开的承诺：**1** 项，其中 **1** 项", home)
        self.assertNotIn("虚构已完成承诺", home)
        self.assertNotIn("虚构未来承诺", home)
        self.assertNotIn("AI 提议的一个任务", home)

    def test_today_deadline_is_not_counted_overdue(self):
        personal = {"tasks": [{"id": "today", "title": "今天的虚构承诺", "created": "2026-01-10", "expected": "结果"}],
                    "events": [{"seq": 1, "task_id": "today", "day": "2026-01-10", "kind": "add", "due": "2026-01-11"}]}
        home = projections([], self.config, personal)["Home.md"]
        self.assertIn("其中 **0** 项", home)
        self.assertIn("今天截止", home)

    def test_actual_method_and_source_status_remain_visible_in_aggregated_views(self):
        self.config["engine"]["name"] = "codex"
        files = projections([self.source("excerpt"), self.source("ai", "claude", False)], self.config)
        for name in ("Daily/2026-01-10.md", f"Wiki/{slug('虚构主题')}.md"):
            self.assertIn("本地摘录，未经语义归纳", files[name])
            self.assertIn("AI 整理，请核对来源", files[name])
            self.assertIn("来源已删除、改名或不再匹配筛选", files[name])
            self.assertIn("最近采集时来源可访问", files[name])

    def test_missing_method_is_not_mislabeled_as_ai(self):
        row = self.source(method=None)
        page = projections([row], self.config)["Sources/fixture.md"]
        self.assertIn("整理方式未记录", page)
        self.assertNotIn("AI 整理", page)


if __name__ == "__main__":
    unittest.main()
