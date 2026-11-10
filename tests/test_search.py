"""Invented catalog records test relevance, content boundaries and dated evidence."""

import copy
import unittest
from unittest.mock import patch

from test_knowledge import WorkspaceFixture
from knowledge.common import KnowledgeError
from knowledge.query import search_catalog
from knowledge.reflection import checkin, task
from knowledge.service import search, sync


def document(identifier="fixture", *, day="2026-01-02", title="资料", topics=None, summary="摘要", body="正文", kind="markdown"):
    return {"document": {"id": identifier, "source": "hidden-source", "origin": "private-name.md", "kind": kind,
                         "day": day, "text": body},
            "summary": {"title": title, "topics": topics or [], "summary": summary,
                        "key_points": [], "decisions": [], "questions": [], "method": "extract"}, "available": True}


class QueryCase(unittest.TestCase):
    def test_empty_query_invalid_filters_and_reversed_dates_are_actionable(self):
        for query in ("", " \t\n", None):
            with self.subTest(query=query), self.assertRaises(KnowledgeError):
                search_catalog([], {}, query)
        for options in ({"since": "2026-1-2"}, {"until": "2026-02-30"}, {"since": 20260101},
                        {"since": "2026-01-03", "until": "2026-01-02"}, {"kind": "unknown"}, {"kind": []}):
            with self.subTest(options=options), self.assertRaises(KnowledgeError):
                search_catalog([], {}, "keyword", **options)
        self.assertEqual(search_catalog([], {}, "keyword", since="2099-01-01"), [])

    def test_serialized_keys_and_metadata_are_not_content(self):
        row = document("secret-id", topics=["主题"])
        for term in ("source", "available", "method", "topics", "document", "markdown", "extract",
                     "hidden-source", "private-name", "secret-id", "2026-01-02"):
            with self.subTest(term=term):
                self.assertEqual(search_catalog([row], {}, term), [])
        row["document"]["text"] = '用户明确写下的 JSON 示例：{"source": "sample"}'
        self.assertTrue(search_catalog([row], {}, "source"), "User-authored JSON remains searchable content")

    def test_keywords_match_and_across_fields_without_semantic_expansion(self):
        rows = [document("match", title="ALPHA 项目", body="记录 delta 结果"),
                document("partial", title="ALPHA 项目", body="只有部分命中")]
        result = search_catalog(rows, {}, "alpha DELTA alpha")
        self.assertEqual([row["file"] for row in result], ["Sources/match.md"])
        self.assertEqual(result[0]["matched_fields"], ["title", "body"])
        self.assertEqual(search_catalog(rows, {}, "同义词拓展"), [])

    def test_title_topic_summary_and_structured_content_rank_before_newer_body(self):
        rows = [document("body", day="2026-01-30", body="needle"),
                document("summary", day="2026-01-25", summary="needle"),
                document("topic", day="2026-01-20", topics=["needle"]),
                document("title", day="2026-01-01", title="needle"),
                document("points", day="2026-01-28")]
        rows[-1]["summary"]["key_points"] = ["needle"]
        hits = search_catalog(rows, {}, "needle")
        self.assertEqual([hit["file"] for hit in hits],
                         ["Sources/title.md", "Sources/topic.md", "Sources/summary.md", "Sources/points.md", "Sources/body.md"])

    def test_kind_and_closed_date_window_filter_actual_document_days(self):
        rows = [document("early", day="2026-01-01", body="needle"),
                document("included", day="2026-01-02", body="needle"),
                document("other-kind", day="2026-01-02", body="needle", kind="codex"),
                document("late", day="2026-01-03", body="needle")]
        hits = search_catalog(rows, {}, "needle", since="2026-01-02", until="2026-01-02", kind="markdown")
        self.assertEqual([hit["file"] for hit in hits], ["Sources/included.md"])
        for kind in ("markdown", "codex", "claude", "export"):
            self.assertEqual(search_catalog([document(body="needle", kind=kind)], {}, "needle", kind=kind)[0]["kind"], kind)

    def test_result_explains_actual_provenance_and_retains_unavailable_history(self):
        row = document(title="needle", topics=["主题"])
        row["available"] = False
        row["summary"]["method"] = "claude"
        before = copy.deepcopy(row)
        hit = search_catalog([row], {}, "needle")[0]
        self.assertEqual(set(hit), {"date", "title", "topics", "file", "kind", "source", "method", "available", "snippet", "matched_fields"})
        self.assertEqual((hit["method"], hit["source"], hit["available"]), ("claude", "hidden-source", False))
        hit["topics"].append("result-only")
        self.assertEqual(row, before)
        del row["summary"]["method"]
        self.assertEqual(search_catalog([row], {}, "needle")[0]["method"], "unknown")

    def test_snippet_is_bounded_and_shows_late_unicode_casefold_hit(self):
        row = document(body="ß" * 600 + " NEEDLE " + "尾" * 1000)
        snippet = search_catalog([row], {}, "needle")[0]["snippet"]
        self.assertLessEqual(len(snippet), 280)
        self.assertIn("NEEDLE", snippet)
        self.assertTrue(snippet.startswith("…"))
        self.assertTrue(snippet.endswith("…"))

    def test_recency_only_breaks_relevance_ties_and_fifty_results_are_stable(self):
        rows = [document(f"fixture-{index:03d}", day=f"2026-01-{index % 28 + 1:02d}", title="needle") for index in range(80)]
        first = search_catalog(rows, {}, "needle")
        second = search_catalog(list(reversed(rows)), {}, "needle")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 50)
        self.assertEqual([hit["date"] for hit in first], sorted((hit["date"] for hit in first), reverse=True))

    def test_checkins_search_blockers_and_lessons_as_self_report(self):
        personal = {"checkins": [{"day": "2026-01-02", "done": ["完成草稿"], "blocked": ["等待虚构接口"], "lessons": ["先确认依赖"]}]}
        hit = search_catalog([], personal, "接口 依赖", kind="checkin")[0]
        self.assertEqual(hit["matched_fields"], ["blocked", "lessons"])
        self.assertEqual((hit["kind"], hit["source"], hit["method"]), ("checkin", "self", "self-report"))
        self.assertEqual(search_catalog([], personal, "blocked"), [])
        self.assertEqual(search_catalog([], personal, "接口", since="2026-01-03"), [])

    def test_task_window_searches_dated_activity_without_later_outcome_leakage(self):
        personal = {"tasks": [{"id": "task-id", "title": "虚构原型", "expected": "可运行演示", "created": "2026-01-01", "source_id": "hidden-link"}],
                    "events": [{"task_id": "task-id", "day": "2026-01-01", "kind": "add", "seq": 1, "due": "2026-01-05"},
                               {"task_id": "task-id", "day": "2026-01-06", "kind": "defer", "seq": 2, "reason": "等待接口"},
                               {"task_id": "task-id", "day": "2026-01-20", "kind": "finish", "seq": 3, "outcome": "验收通过"}]}
        hit = search_catalog([], personal, "等待接口", since="2026-01-05", until="2026-01-10", kind="task")[0]
        self.assertEqual((hit["date"], hit["matched_fields"]), ("2026-01-06", ["reason"]))
        self.assertEqual(search_catalog([], personal, "验收通过", until="2026-01-10"), [])
        self.assertEqual(search_catalog([], personal, "原型", since="2026-01-07", until="2026-01-10"), [])
        self.assertEqual(search_catalog([], personal, "演示", until="2026-01-10")[0]["matched_fields"], ["expected"])
        self.assertEqual(search_catalog([], personal, "验收通过")[0]["date"], "2026-01-20")
        self.assertEqual(search_catalog([], personal, "hidden-link"), [])


class SearchServiceCase(WorkspaceFixture, unittest.TestCase):
    def test_existing_api_and_filtered_search_do_not_call_sources_models_or_network(self):
        self.note(body="# 虚构接口资料\n\n记录一个可复核结果。")
        self.configure()
        sync(self.root)
        checkin(self.root, "2026-01-02", [], ["等待虚构接口"], ["先验证依赖"])
        identifier = task(self.root, "add", "交付虚构结果", day="2026-01-02", expected="可复核的演示")["id"]
        task(self.root, "finish", identifier, day="2026-01-03", outcome="虚构验收通过")
        with patch("knowledge.service.read_source") as reader, patch("knowledge.service.summarize") as model, \
                patch("socket.create_connection", side_effect=AssertionError("Search must be offline")):
            self.assertTrue(search(self.root, "接口"))
            hit = search(self.root, "验收通过", since="2026-01-03", until="2026-01-03", kind="task")[0]
            self.assertEqual(hit["file"], f"Tasks.md#task-{identifier}")
            self.assertEqual(hit["method"], "self-report")
            reader.assert_not_called()
            model.assert_not_called()
