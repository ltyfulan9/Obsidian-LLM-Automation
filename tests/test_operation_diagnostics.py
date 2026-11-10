"""Invented operation metadata: failures, live runs and read-only diagnosis."""

import hashlib
import io
import json
import sqlite3
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from unittest.mock import patch

from test_knowledge import WorkspaceFixture
from knowledge.cli import main
from knowledge.common import KnowledgeError, workspace_lock, write_json
from knowledge.doctor import doctor
from knowledge.runstate import status
from knowledge.service import sync


class OperationDiagnosticsCase(WorkspaceFixture, unittest.TestCase):
    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in self.root.rglob("*") if path.is_file()}

    def inspect(self, attempt=None, busy=False, success=None):
        with patch("knowledge.doctor.operation_status", return_value={"last_attempt": attempt, "workspace_busy": busy, "last_run": success}), \
                patch("knowledge.doctor.private_target", side_effect=AssertionError("Unexpected network")):
            return doctor(self.root)

    def operation(self, result):
        return next(check for check in result["checks"] if check["id"] == "operation")

    def test_latest_failure_is_not_hidden_by_retained_success(self):
        attempt = {"status": "failed", "phase": "publish", "saved": {"catalog": True, "rendered": True, "published": False},
                   "error": "publish_failed", "next_step": "Run knowledge publish for this workspace."}
        result = self.inspect(attempt, success={"time": "2026-01-09T10:00:00Z"})
        self.assertFalse(result["ok"])
        check = self.operation(result)
        self.assertEqual(check["status"], "error")
        self.assertIn("failed during publication", check["message"])
        self.assertIn("Confirmed stages: catalog, pages", check["message"])
        self.assertIn("earlier success does not describe", check["message"])
        self.assertIn("knowledge publish", check["next_step"])

    def test_interrupted_attempt_reports_saved_fact_and_appropriate_retry(self):
        attempt = {"status": "interrupted", "recorded_status": "running", "phase": "render", "saved": {"catalog": True},
                   "next_step": "Resolve page conflicts, then run knowledge build."}
        result = self.inspect(attempt)
        self.assertFalse(result["ok"])
        self.assertIn("interrupted during page generation", self.operation(result)["message"])
        self.assertIn("knowledge build", self.operation(result)["next_step"])

    def test_active_run_does_not_report_transient_generated_edits_as_corruption(self):
        (self.root / "Home.md").write_text("Invented in-progress generation", encoding="utf-8")
        write_json(self.root / ".knowledge/render-journal.json", {"invented": "in progress"})
        before = self.snapshot()
        attempt = {"status": "running", "phase": "render", "saved": {"catalog": True}}
        with patch("knowledge.doctor.registry", side_effect=AssertionError("Read live generated pages")), \
                patch("knowledge.doctor.sqlite3.connect", side_effect=AssertionError("Read live catalog")):
            result = self.inspect(attempt, busy=True)
        self.assertTrue(result["ok"])
        self.assertEqual(self.operation(result)["status"], "warning")
        self.assertIn("active", self.operation(result)["message"])
        for identifier in ("catalog", "generated"):
            self.assertIn("deferred", next(check for check in result["checks"] if check["id"] == identifier)["message"])
        self.assertEqual(self.snapshot(), before)

    def test_running_metadata_with_unknown_lock_state_is_not_called_interrupted(self):
        result = self.inspect({"status": "running", "phase": "collect", "saved": {}}, busy=None)
        check = self.operation(result)
        self.assertEqual(check["status"], "warning")
        self.assertIn("not confirmed", check["message"])
        self.assertNotIn("interrupted", check["message"])
        self.assertIn("do not delete run.lock", check["next_step"])

    def test_legacy_success_without_attempt_is_not_claimed_as_recent_success(self):
        result = self.inspect(success={"time": "2026-01-09T10:00:00Z"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.operation(result)["status"], "warning")
        self.assertIn("no latest-attempt record", self.operation(result)["message"])

    def test_success_does_not_claim_native_scheduler_is_installed(self):
        result = self.inspect({"status": "succeeded", "phase": "complete", "saved": {"catalog": True, "rendered": True}})
        self.assertTrue(result["ok"])
        self.assertIn("scheduler installation was not queried", self.operation(result)["message"])

    def test_metadata_error_keeps_data_and_does_not_echo_original_error(self):
        before = self.snapshot()
        with patch("knowledge.doctor.operation_status", side_effect=KnowledgeError("invented-secret-do-not-print")):
            result = doctor(self.root)
        self.assertFalse(result["ok"])
        self.assertNotIn("invented-secret-do-not-print", json.dumps(result))
        self.assertEqual(self.snapshot(), before)

    def test_home_explains_status_is_live_and_markdown_is_not(self):
        home = (self.root / "Home.md").read_text(encoding="utf-8")
        self.assertIn("不是实时运行面板", home)
        self.assertIn('knowledge status --workspace "你的知识库目录" --format text', home)
        self.assertIn("knowledge doctor", home)
        self.assertNotIn("Latest attempt is running", home)

    def test_real_failed_sync_keeps_last_success_and_readonly_doctor_reports_failure(self):
        note = self.note()
        self.configure()
        success = sync(self.root)
        card = next((self.root / "Sources").glob("*.md"))
        retained = card.read_bytes()
        note.unlink()
        self.source.rmdir()
        with self.assertRaises(KnowledgeError):
            sync(self.root)
        saved = status(self.root)
        self.assertEqual(saved["last_run"]["run_id"], success["run_id"])
        self.assertEqual(saved["last_attempt"]["status"], "failed")
        self.assertEqual(saved["last_attempt"]["phase"], "collect")
        before = self.snapshot()
        result = doctor(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("failed during source collection", self.operation(result)["message"])
        self.assertEqual(card.read_bytes(), retained)
        self.assertEqual(self.snapshot(), before)

    def test_correct_table_names_with_missing_owned_columns_are_rejected_readonly(self):
        database = self.root / ".knowledge/catalog.sqlite3"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("DROP TABLE documents")
            connection.execute("CREATE TABLE documents (id TEXT PRIMARY KEY)")
        before = self.snapshot()
        result = doctor(self.root)
        self.assertFalse(result["ok"])
        check = next(check for check in result["checks"] if check["id"] == "catalog")
        self.assertEqual(check["status"], "error")
        self.assertIn("restore", check["next_step"])
        self.assertEqual(self.snapshot(), before)

    def test_blocked_cli_sync_is_not_logged_as_previous_success_or_releases_owner_lock(self):
        success = sync(self.root)
        state_file = self.root / ".knowledge/run-state.json"
        before = state_file.read_bytes()
        with workspace_lock(self.root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["sync", "--workspace", str(self.root), "--log"])
            self.assertEqual(code, 1)
            self.assertEqual(state_file.read_bytes(), before)
            with self.assertRaises(KnowledgeError):
                with workspace_lock(self.root):
                    self.fail("Blocked CLI released another operation's lock")
        event = json.loads((self.root / ".knowledge/scheduler.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((event["status"], event["phase"], event["error"]), ("blocked", "start", "start_failed"))
        self.assertNotEqual(event["run_id"], success["run_id"])
        self.assertEqual(status(self.root)["last_run"]["run_id"], success["run_id"])

    def test_blocked_cli_sync_does_not_claim_another_running_attempt(self):
        success = sync(self.root)
        state_file = self.root / ".knowledge/run-state.json"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        active_id = "a" * 32
        state["last_attempt"].update(status="running", phase="collect", run_id=active_id, finished_at=None)
        write_json(state_file, state)
        before = state_file.read_bytes()
        with workspace_lock(self.root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["sync", "--workspace", str(self.root), "--log"])
            self.assertEqual(code, 1)
            self.assertEqual(state_file.read_bytes(), before)
            self.assertEqual(status(self.root)["last_attempt"]["run_id"], active_id)
            self.assertEqual(status(self.root)["last_attempt"]["status"], "running")
            self.assertTrue(status(self.root)["workspace_busy"])
        event = json.loads((self.root / ".knowledge/scheduler.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(event["status"], "blocked")
        self.assertNotEqual(event["run_id"], active_id)
        self.assertEqual(status(self.root)["last_run"]["run_id"], success["run_id"])


if __name__ == "__main__":
    unittest.main()
