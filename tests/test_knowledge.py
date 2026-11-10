"""Synthetic fixtures only: never read the operator's real notes or CLI sessions."""

import json
import plistlib
import shutil
import subprocess
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from knowledge.catalog import Catalog
from knowledge.cli import main
from knowledge.common import KnowledgeError, clean_text, day_of, read_json, write_json
from knowledge.ingest import Document, native_messages, read_source
from knowledge.publish import private_target, publish
from knowledge.schedule import definition
from knowledge.service import initialize, load_config, rebuild, search, sync
from knowledge.scope import sync_scope
from knowledge.summarize import SCHEMA, summarize, validate


class WorkspaceFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="knowledge-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "wiki"
        self.source = self.base / "input"
        self.source.mkdir()
        initialize(self.root)
        self.config = load_config(self.root)
        self.config["timezone"] = "+08:00"

    def configure(self, kind="markdown", **options):
        self.config["sources"] = [{"name": "fixture", "kind": kind, "path": str(self.source), **options}]
        write_json(self.root / ".knowledge/config.json", self.config)

    def note(self, name="2026-01-02.md", body="# Python 笔记\n\n学习 Python 与知识库。\n"):
        path = self.source / name
        path.write_text(body, encoding="utf-8")
        return path


class WorkspaceCase(WorkspaceFixture, unittest.TestCase):
    def test_plan_describes_summaries_without_reading_sources_or_exposing_paths(self):
        self.configure("claude")
        with patch("knowledge.service.read_source") as reader, patch("knowledge.service.summarize") as model:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["plan", "--workspace", str(self.root)]), 0)
            value = json.loads(output.getvalue())
            self.assertFalse(value["raw_archive"])
            self.assertEqual(value["sources"][0]["kind"], "claude")
            self.assertNotIn(str(self.source), output.getvalue())
            reader.assert_not_called()
            model.assert_not_called()

    def test_generated_scope_page_matches_config_and_omits_absolute_paths(self):
        self.note()
        self.configure()
        sync(self.root)
        page = (self.root / "Sync.md").read_text(encoding="utf-8")
        self.assertIn("AI 对话内容小结", page)
        self.assertIn("完整对话正文归档未启用", page)
        self.assertNotIn(str(self.source), page)

    def test_recent_days_persists_fixed_cutoff(self):
        with patch("knowledge.cli.datetime") as clock, redirect_stdout(io.StringIO()):
            clock.now.return_value = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
            code = main(["source", "--workspace", str(self.root), "claude", str(self.source),
                         "--name", "conversations", "--recent-days", "7"])
        self.assertEqual(code, 0)
        source = load_config(self.root)["sources"][0]
        self.assertEqual(source["since"], "2026-11-04")

    @unittest.skipUnless(shutil.which("git"), "Git required")
    def test_private_publication_roundtrip_and_archive_deletion(self):
        remote = self.base / "synthetic-remote.git"

        def git(*args):
            result = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

        git("init", "--bare", str(remote))
        git("init", "-b", "main")
        git("config", "user.name", "Synthetic Fixture")
        git("config", "user.email", "fixture@example.invalid")
        git("remote", "add", "origin", str(remote))
        self.note()
        self.configure()
        self.config["include_raw"] = True
        write_json(self.root / ".knowledge/config.json", self.config)
        sync(self.root)
        with patch("knowledge.publish.private_target", return_value="example/private-fixture"):
            publish(self.root, include_raw=True)
        self.assertEqual(git("ls-files", ".knowledge"), "")
        self.assertTrue(git("ls-files", "Archive"))
        self.config["include_raw"] = False
        write_json(self.root / ".knowledge/config.json", self.config)
        rebuild(self.root)
        with patch("knowledge.publish.private_target", return_value="example/private-fixture"):
            publish(self.root)
        self.assertEqual(git("ls-files", "Archive"), "")
        self.assertEqual(git("rev-parse", "HEAD"), git("rev-parse", "origin/main"))

    def test_repeated_sync_has_no_changes_or_duplicate_records(self):
        original = self.note()
        before = original.read_bytes()
        self.configure()
        first, second = sync(self.root), sync(self.root)
        self.assertEqual((first["updated"], second["updated"], second["unchanged"]), (1, 0, 1))
        self.assertEqual(len(list((self.root / "Sources").glob("*.md"))), 1)
        self.assertEqual(original.read_bytes(), before)
        self.assertTrue((self.root / "Daily/2026-01-02.md").exists())
        self.assertTrue(list((self.root / "Wiki").glob("*.md")))
        self.assertEqual(second["engine"], "extract")

    def test_changed_note_updates_same_card(self):
        path = self.note()
        self.configure()
        sync(self.root)
        original = list((self.root / "Sources").glob("*.md"))[0]
        path.write_text("# Python 新笔记\n\n新知识与新的结论。", encoding="utf-8")
        self.assertEqual(sync(self.root)["updated"], 1)
        self.assertTrue(original.exists())
        self.assertIn("新知识", original.read_text(encoding="utf-8"))

    def test_deleted_sources_are_retained_and_marked(self):
        path = self.note()
        self.configure()
        sync(self.root)
        path.unlink()
        sync(self.root)
        card = next((self.root / "Sources").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("来源已删除", card)
        self.assertTrue((self.root / "Daily/2026-01-02.md").exists())

    def test_handwritten_notes_are_preserved(self):
        note = self.root / "Notes/my-note.md"
        note.write_text("Handwritten", encoding="utf-8")
        self.note()
        self.configure()
        sync(self.root)
        rebuild(self.root)
        self.assertEqual(note.read_text(), "Handwritten")

    def test_manual_generated_edit_blocks_overwrite(self):
        home = self.root / "Home.md"
        home.write_text("My manual edit", encoding="utf-8")
        with self.assertRaisesRegex(KnowledgeError, "manual changes"):
            rebuild(self.root)
        self.assertEqual(home.read_text(), "My manual edit")

    def test_secret_blocks_before_model_and_catalog_advance(self):
        self.note(body="# Secret\n" + "sk-" + "a" * 35)
        self.configure()
        with patch("knowledge.service.summarize") as model:
            with self.assertRaisesRegex(KnowledgeError, "Secret-like"):
                sync(self.root)
            model.assert_not_called()
        catalog = Catalog(self.root)
        self.addCleanup(catalog.close)
        self.assertEqual(catalog.rows(), [])

    def test_summary_failure_rolls_back_all_documents(self):
        self.note()
        self.note("2026-01-03.md")
        self.configure()
        valid = {"title": "T", "summary": "S", "topics": ["Python"], "key_points": [], "decisions": [], "questions": []}
        with patch("knowledge.service.summarize", side_effect=[valid, KnowledgeError("provider error")]):
            with self.assertRaises(KnowledgeError):
                sync(self.root)
        catalog = Catalog(self.root)
        self.addCleanup(catalog.close)
        self.assertEqual(catalog.rows(), [])

    def test_source_filters_and_obsidian_state_are_excluded(self):
        self.note()
        self.note("skip.md")
        (self.source / ".obsidian").mkdir()
        (self.source / ".obsidian/private.md").write_text("Private")
        self.configure(exclude=["skip.md"])
        self.assertEqual(sync(self.root)["documents"], 1)

    def test_output_may_not_be_inside_source(self):
        self.config["sources"] = [{"name": "unsafe", "kind": "markdown", "path": str(self.base)}]
        write_json(self.root / ".knowledge/config.json", self.config)
        with self.assertRaisesRegex(KnowledgeError, "must not contain"):
            sync(self.root)

    def test_output_path_alias_is_canonicalized_before_boundary_check(self):
        source = {"name": "fixture", "kind": "markdown", "path": str(self.base)}
        alias = self.base / "wiki" / ".." / "wiki"
        with self.assertRaisesRegex(KnowledgeError, "must not contain"):
            read_source(source, self.config, alias)

    def test_canvas_edges_and_files_are_valid(self):
        self.note()
        self.configure()
        sync(self.root)
        canvas = read_json(self.root / "Maps/Knowledge.canvas")
        ids = {node["id"] for node in canvas["nodes"]}
        self.assertEqual(len(ids), len(canvas["nodes"]))
        for node in canvas["nodes"]:
            self.assertTrue((self.root / node["file"]).exists())
        for edge in canvas["edges"]:
            self.assertIn(edge["fromNode"], ids)
            self.assertIn(edge["toNode"], ids)

    def test_archive_is_opt_in_and_removable(self):
        self.note()
        self.configure()
        sync(self.root)
        self.assertFalse((self.root / "Archive").exists())
        self.config["include_raw"] = True
        write_json(self.root / ".knowledge/config.json", self.config)
        rebuild(self.root)
        self.assertEqual(len(list((self.root / "Archive").glob("*.md"))), 1)
        self.config["include_raw"] = False
        write_json(self.root / ".knowledge/config.json", self.config)
        rebuild(self.root)
        self.assertFalse(list((self.root / "Archive").glob("*.md")))

    def test_search_matches_topic_and_body(self):
        self.note()
        self.configure()
        sync(self.root)
        self.assertEqual(len(search(self.root, "Python")), 1)
        self.assertEqual(search(self.root, "nonexistent"), [])

    def test_public_push_refused_before_source_read(self):
        self.configure()
        with patch("knowledge.service.private_target", side_effect=KnowledgeError("public")), patch("knowledge.service.read_source") as reader:
            with self.assertRaisesRegex(KnowledgeError, "public"):
                sync(self.root, push=True)
            reader.assert_not_called()

    def test_missing_source_fails_without_marking_data_deleted(self):
        self.note()
        self.configure()
        sync(self.root)
        self.config["sources"][0]["path"] = str(self.base / "missing")
        write_json(self.root / ".knowledge/config.json", self.config)
        with self.assertRaises(KnowledgeError):
            sync(self.root)
        catalog = Catalog(self.root)
        self.addCleanup(catalog.close)
        self.assertTrue(catalog.rows()[0]["available"])

    def test_init_does_not_overwrite_existing_entrance(self):
        other = self.base / "existing"
        other.mkdir()
        (other / "Home.md").write_text("original")
        with self.assertRaises(KnowledgeError):
            initialize(other)
        self.assertEqual((other / "Home.md").read_text(), "original")


class AdapterCase(WorkspaceFixture, unittest.TestCase):
    def jsonl(self, records):
        path = self.source / "session.jsonl"
        path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")
        return path

    def test_codex_native_deduplicates_events_and_excludes_tools_system_reasoning(self):
        records = [
            {"type": "event_msg", "payload": {"type": "user_message", "message": "duplicate"}},
            {"timestamp": "2026-01-02T16:10:00Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "How to learn Python?"}]}},
            {"timestamp": "2026-01-02T16:20:00Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Practice with examples."}]}},
            {"type": "response_item", "payload": {"type": "reasoning", "content": "hidden"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "output": "tool secret"}},
            {"type": "response_item", "payload": {"type": "message", "role": "system", "content": "system secret"}},
        ]
        self.jsonl(records)
        self.configure("codex")
        documents = read_source(self.config["sources"][0], self.config, self.root)
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].day, "2026-01-03")
        for excluded in ("duplicate", "hidden", "tool secret", "system secret"):
            self.assertNotIn(excluded, documents[0].text)

    def test_cross_day_conversation_becomes_two_daily_records(self):
        self.jsonl([{"type": "user", "timestamp": stamp, "message": {"role": "user", "content": text}}
                    for stamp, text in [("2026-01-02T10:00:00Z", "First question"), ("2026-01-03T10:00:00Z", "Second question")]])
        self.configure("claude")
        self.assertEqual(sync(self.root)["documents"], 2)

    def test_since_filters_message_dates_without_truncating_newer_days(self):
        self.jsonl([{"type": "user", "timestamp": stamp, "message": {"role": "user", "content": text}}
                    for stamp, text in [("2026-01-01T10:00:00Z", "Old message"), ("2026-01-05T10:00:00Z", "New message")]])
        self.configure("claude", since="2026-01-04")
        self.assertEqual(sync(self.root)["documents"], 1)
        self.assertTrue((self.root / "Daily/2026-01-05.md").exists())
        self.assertFalse((self.root / "Daily/2026-01-01.md").exists())

    def test_repeated_automation_only_summarizes_changed_conversation(self):
        path = self.jsonl([{"type": "user", "timestamp": "2026-01-05T10:00:00Z", "message": {"content": "Synthetic question"}}])
        self.configure("claude")
        summary = {"title": "Synthetic chat", "summary": "A conversation summary", "topics": ["知识管理"],
                   "key_points": ["A reusable point"], "decisions": ["An explicit choice"], "questions": ["An open question"]}
        with patch("knowledge.service.summarize", return_value=summary) as model:
            first = sync(self.root)
            second = sync(self.root)
            self.assertEqual((first["updated"], second["updated"], model.call_count), (1, 0, 1))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"type": "assistant", "timestamp": "2026-01-05T10:01:00Z",
                                         "message": {"content": "Synthetic answer"}}) + "\n")
            self.assertEqual(sync(self.root)["updated"], 1)
            self.assertEqual(model.call_count, 2)
        topic = next((self.root / "Wiki").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("An explicit choice", topic)
        self.assertIn("An open question", topic)

    def test_claude_tools_thinking_and_sidechains_are_excluded(self):
        records = [
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "tool data"}]}},
            {"type": "assistant", "isSidechain": True, "message": {"content": "subagent"}},
            {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": "visible"}]}},
        ]
        self.assertEqual(native_messages(records, "claude"), [("assistant", "visible", None)])

    def test_generic_and_claude_export_json(self):
        (self.source / "export.json").write_text(json.dumps([
            {"uuid": "synthetic-chat", "created_at": "2026-01-02T10:00:00Z", "chat_messages": [
                {"sender": "human", "text": "Tell me about databases"},
                {"sender": "assistant", "text": "Indexes speed up some reads."}]}]), encoding="utf-8")
        self.configure("export")
        self.assertEqual(sync(self.root)["documents"], 1)

    def test_flat_generic_jsonl(self):
        self.jsonl([{"role": "user", "content": "Hello", "timestamp": "2026-01-02T00:00:00Z"},
                    {"role": "assistant", "content": "Hi", "timestamp": "2026-01-02T00:00:01Z"}])
        self.configure("export")
        self.assertEqual(sync(self.root)["documents"], 1)

    def test_partial_last_line_is_retried_and_interior_corruption_fails(self):
        path = self.jsonl([{"type": "user", "message": {"content": "Complete message"}}])
        with path.open("a") as stream:
            stream.write('{"type":')
        self.configure("claude")
        self.assertEqual(sync(self.root)["documents"], 1)
        path.write_text('{broken}\n{"type": "user"}\n')
        with self.assertRaisesRegex(KnowledgeError, "Malformed JSONL"):
            sync(self.root)


class PureCase(unittest.TestCase):
    def test_interval_schedules_for_both_platforms(self):
        root = Path("/synthetic/wiki")
        plist = plistlib.loads(definition(root, "macos", 21, 0, interval_minutes=30).encode())
        self.assertEqual(plist["StartInterval"], 1800)
        self.assertTrue(plist["RunAtLoad"])
        self.assertNotIn("StartCalendarInterval", plist)
        windows = definition(root, "windows", 21, 0, interval_minutes=30)
        self.assertNotIn('encoding=', windows.splitlines()[0])
        xml = ET.fromstring(windows)
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(xml.find(".//t:TimeTrigger/t:Repetition/t:Interval", ns).text, "PT30M")
        self.assertIsNone(xml.find(".//t:CalendarTrigger", ns))
        with self.assertRaises(KnowledgeError):
            definition(root, "macos", 21, 0, interval_minutes=0)

    def test_timezone_conversion_and_offsets(self):
        self.assertEqual(day_of("2026-01-01T20:00:00Z", 0, "+08:00"), "2026-01-02")
        self.assertEqual(day_of("2026-01-01T01:00:00Z", 0, "-05:00"), "2025-12-31")

    def test_redactions(self):
        result = clean_text("C:\\Users\\fixture\\Notes /Users/example/Notes person@example.invalid", {})
        self.assertNotIn("fixture", result)
        self.assertNotIn("/Users/example", result)
        self.assertNotIn("person@", result)

    def test_output_schema_rejects_wrong_types_and_extras(self):
        with self.assertRaises(KnowledgeError):
            validate({"title": "a", "summary": "b"}, {})
        value = {"title": "a", "summary": "b", "topics": "not a list", "key_points": [], "decisions": [], "questions": []}
        with self.assertRaises(KnowledgeError):
            validate(value, {})

    def test_long_conversation_is_chunked_without_truncation(self):
        document = Document("id", "fixture", "chat", "export", "2026-01-02", "Title", "x" * 4000 + "TAIL", [])
        valid = {"title": "a", "summary": "b", "topics": ["主题"], "key_points": [], "decisions": [], "questions": []}
        with patch("knowledge.summarize.invoke_cli", return_value=valid) as runner:
            summarize(document, {"name": "codex", "chunk_chars": 2000}, {})
        prompts = [call.args[0] for call in runner.call_args_list]
        self.assertTrue(any("TAIL" in prompt for prompt in prompts))
        self.assertEqual(len(prompts), 4)

    def test_native_scheduler_definitions_quote_paths(self):
        root = Path("/Users/example/Personal Wiki")
        plist = plistlib.loads(definition(root, "macos", 21, 15, True, "/opt/python/bin/python3").encode())
        self.assertIn(str(root), plist["ProgramArguments"])
        self.assertIn("--push", plist["ProgramArguments"])
        self.assertEqual(plist["StartCalendarInterval"], {"Hour": 21, "Minute": 15})
        xml = ET.fromstring(definition(Path("C:/Notes/Personal Wiki"), "windows", 21, 0, python="C:/Python/python.exe"))
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertIn('"', xml.find(".//t:Arguments", ns).text)

    def test_public_github_target_rejected(self):
        root = Path.cwd()
        outputs = [str(root), "main", "https://github.com/example/public-wiki.git", "false"]
        with patch("knowledge.publish.shutil.which", return_value="binary"), patch("knowledge.publish.run", side_effect=outputs):
            with self.assertRaisesRegex(KnowledgeError, "public"):
                private_target(root)

    def test_private_github_target_accepted(self):
        root = Path.cwd()
        outputs = [str(root), "main", "git@github.com:example/private-wiki.git", "true"]
        with patch("knowledge.publish.shutil.which", return_value="binary"), patch("knowledge.publish.run", side_effect=outputs):
            self.assertEqual(private_target(root), "example/private-wiki")


if __name__ == "__main__":
    unittest.main()
