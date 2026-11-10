"""Offline, read-only diagnostics and actionable configuration validation."""

import copy
import hashlib
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from test_knowledge import WorkspaceFixture
from knowledge.common import KnowledgeError, write_json
from knowledge.config import validate_config
from knowledge.doctor import doctor
from knowledge.service import DEFAULT_CONFIG, initialize, load_config, rebuild, sync


class ConfigurationCase(unittest.TestCase):
    def test_validation_rejects_wrong_types_without_changing_input(self):
        invalid = [
            {"version": 2.0}, {"sources": {}}, {"engine": []},
            {"engine": {"name": []}}, {"engine": {"name": "extract", "timeout_seconds": True}},
            {"engine": {"name": "extract", "retries": 4}}, {"timezone": "/invalid/zone"},
            {"privacy": {"redact_emails": "false"}}, {"include_raw": "false"},
            {"magpie": {"max_kib": "64"}}, {"magpie": []},
        ]
        source = {"name": "fixture", "kind": "markdown", "path": "/synthetic/input"}
        for field, value in (("name", 7), ("kind", []), ("path", []), ("path", "\x00"),
                             ("since", 20260101), ("since", "2026-1-1"), ("include", [7])):
            invalid.append({"sources": [{**source, field: value}]})
        for changes in invalid:
            value = {**copy.deepcopy(DEFAULT_CONFIG), **changes}
            before = copy.deepcopy(value)
            with self.subTest(changes=changes), self.assertRaises(KnowledgeError):
                validate_config(value)
            self.assertEqual(value, before)
        with self.assertRaises(KnowledgeError):
            validate_config([])


class DiagnosticsCase(WorkspaceFixture, unittest.TestCase):
    def test_manual_entry_upgrades_missing_guide_without_sync(self):
        from knowledge.reflection import checkin
        guide = self.root / "Notes/README.md"
        guide.unlink()
        checkin(self.root, "2026-01-02", ["Invented observed result"], [], [])
        self.assertTrue(guide.is_file())
        guide.write_text("My handwritten entrance", encoding="utf-8")
        checkin(self.root, "2026-01-02", ["Another invented result"], [], [])
        self.assertEqual(guide.read_text(encoding="utf-8"), "My handwritten entrance")

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in self.root.rglob("*") if path.is_file()}

    def test_default_doctor_is_readonly_offline_and_does_not_open_source_content(self):
        note = self.note(body="# Private invented body\n\nShould not be opened by doctor.")
        self.configure()
        before = self.snapshot()
        original_read = type(note).read_text

        def read(path, *args, **kwargs):
            if path.is_relative_to(self.source):
                self.fail("Doctor opened source content")
            return original_read(path, *args, **kwargs)

        original_connect = sqlite3.connect
        with patch("pathlib.Path.read_text", read), \
                patch("knowledge.doctor.sqlite3.connect", wraps=original_connect) as connections, \
                patch("knowledge.doctor.private_target", side_effect=AssertionError("Unexpected network")), \
                patch("knowledge.service.read_source") as reader, patch("knowledge.service.summarize") as model:
            result = doctor(self.root)
        self.assertTrue(result["ok"])
        reader.assert_not_called()
        model.assert_not_called()
        self.assertTrue(connections.called)
        for call in connections.call_args_list:
            self.assertIn("mode=ro", call.args[0])
            self.assertTrue(call.kwargs["uri"])
        self.assertEqual(self.snapshot(), before)

    def test_missing_workspace_does_not_initialize_anything(self):
        path = self.base / "missing"
        result = doctor(path)
        self.assertFalse(result["ok"])
        self.assertFalse(path.exists())
        self.assertTrue(result["checks"][0]["next_step"])

    def test_invalid_persisted_configuration_is_reported_without_modifying_it(self):
        self.config["sources"] = [{"name": 7, "kind": "markdown", "path": str(self.source)}]
        write_json(self.root / ".knowledge/config.json", self.config)
        before = self.snapshot()
        result = doctor(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("sources[0].name", result["checks"][-1]["message"])
        with self.assertRaises(KnowledgeError):
            load_config(self.root)
        self.assertEqual(self.snapshot(), before)

    def test_source_missing_or_generated_output_is_actionable(self):
        for path in (self.base / "missing", self.root, self.root / "Wiki"):
            self.config["sources"] = [{"name": "fixture", "kind": "markdown", "path": str(path)}]
            write_json(self.root / ".knowledge/config.json", self.config)
            result = doctor(self.root)
            with self.subTest(path=path):
                self.assertFalse(result["ok"])
                check = next(item for item in result["checks"] if item["id"] == "source:fixture")
                self.assertEqual(check["status"], "error")
                self.assertTrue(check["next_step"])

    def test_nested_sources_warn_but_notes_are_valid_readonly_inputs(self):
        child = self.source / "nested"
        child.mkdir()
        self.config["sources"] = [
            {"name": "all", "kind": "markdown", "path": str(self.source)},
            {"name": "nested", "kind": "markdown", "path": str(child)},
            {"name": "handwritten", "kind": "markdown", "path": str(self.root / "Notes")},
        ]
        write_json(self.root / ".knowledge/config.json", self.config)
        result = doctor(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(next(item for item in result["checks"] if item["id"].startswith("overlap:"))["status"], "warning")

    def test_missing_engine_and_failed_private_guard_do_not_call_provider(self):
        self.config["engine"] = {"name": "codex", "command": str(self.base / "missing-cli")}
        write_json(self.root / ".knowledge/config.json", self.config)
        with patch("knowledge.doctor.private_target", side_effect=KnowledgeError("unverified")) as guard:
            result = doctor(self.root, check_publish=True)
        self.assertFalse(result["ok"])
            guard.assert_called_once_with(self.root.resolve())
        self.assertEqual({item["id"] for item in result["checks"] if item["status"] == "error"}, {"engine", "publish"})

    def test_corrupt_catalog_is_not_replaced(self):
        database = self.root / ".knowledge/catalog.sqlite3"
        database.write_bytes(b"invented broken sqlite fixture")
        before = self.snapshot()
        result = doctor(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(next(item for item in result["checks"] if item["id"] == "catalog")["status"], "error")
        self.assertEqual(self.snapshot(), before)

    def test_older_catalog_is_not_upgraded_by_readonly_doctor(self):
        database = self.root / ".knowledge/catalog.sqlite3"
        with closing(sqlite3.connect(database)) as connection, connection:
            for name in ("checkins", "commitments", "commitment_events"):
                connection.execute("DROP TABLE " + name)
        before = self.snapshot()
        result = doctor(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(next(item for item in result["checks"] if item["id"] == "catalog")["status"], "warning")
        self.assertEqual(self.snapshot(), before)

    def test_manual_generated_edit_is_reported_and_preserved(self):
        (self.root / "Home.md").write_text("My invented manual change", encoding="utf-8")
        before = self.snapshot()
        result = doctor(self.root)
        self.assertFalse(result["ok"])
        check = next(item for item in result["checks"] if item["id"] == "generated")
        self.assertIn("Home.md", check["message"])
        self.assertEqual(self.snapshot(), before)

    def test_guide_is_created_for_upgrade_but_existing_handwriting_is_preserved(self):
        guide = self.root / "Notes/README.md"
        self.assertIn("默认入口", guide.read_text(encoding="utf-8"))
        guide.unlink()
        before = self.snapshot()
        doctor(self.root)
        self.assertFalse(guide.exists())
        self.assertEqual(self.snapshot(), before)
        rebuild(self.root)
        self.assertTrue(guide.exists())
        guide.write_bytes(b"My handwritten entry\r\n")
        rebuild(self.root)
        sync(self.root)
        self.assertEqual(guide.read_bytes(), b"My handwritten entry\r\n")

    def test_initialization_preserves_existing_notes_guide(self):
        root = self.base / "another-wiki"
        (root / "Notes").mkdir(parents=True)
        guide = root / "Notes/README.md"
        guide.write_bytes(b"Keep original guide\r\n")
        initialize(root)
        self.assertEqual(guide.read_bytes(), b"Keep original guide\r\n")
