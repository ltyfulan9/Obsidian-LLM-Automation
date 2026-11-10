"""Restore and failure-status journeys use only offline invented workspaces."""

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from knowledge.catalog import Catalog
from knowledge.cli import main


class RecoveryJourneyCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="knowledge-recovery-journey-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "original"
        self.bundle = self.base / "state.zip"
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.model = stack.enter_context(patch("knowledge.summarize.invoke_cli", side_effect=AssertionError("No model during recovery")))
        self.network = stack.enter_context(patch("urllib.request.urlopen", side_effect=AssertionError("No fetching during recovery")))
        stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Recovery stays offline")))
        self.remote = stack.enter_context(patch("knowledge.publish.private_target", side_effect=AssertionError("No implicit GitHub check")))
        self.demo = self.json_command("demo")

    def invoke(self, command, *arguments, workspace=None):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main([command, "--workspace", str(workspace or self.root), *arguments])
        return code, output.getvalue(), errors.getvalue()

    def json_command(self, command, *arguments, workspace=None):
        code, output, errors = self.invoke(command, *arguments, workspace=workspace)
        self.assertEqual(code, 0, errors)
        return json.loads(output)

    def personal_state(self, root):
        catalog = Catalog(root)
        try:
            return catalog.personal_state()
        finally:
            catalog.close()

    def hashes(self, root):
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob("*") if path.is_file()}

    def test_backup_restore_build_search_and_review_preserve_knowledge(self):
        identifier = self.demo["task_id"]
        outcome = "虚构恢复验收：三个观察栏目已经通过核对"
        self.json_command("task", "finish", identifier, "--outcome", outcome)
        self.json_command("checkin", "--done", "虚构恢复验收：确认了观察记录", "--lesson", "虚构教训：保留实际证据")
        note = self.root / "Notes/保留的手写说明.md"
        note.write_text("虚构手写资料，恢复后应保持原样。", encoding="utf-8")
        expected = self.personal_state(self.root)
        backup = self.json_command("backup", "--output", str(self.bundle))
        self.assertEqual(Path(backup["backup"]).resolve(), self.bundle.resolve())
        self.assertGreater(backup["files"], 0)
        self.assertGreater(backup["bytes"], 0)
        restored = self.base / "恢复 知识库"
        preview = self.json_command("restore", "--input", str(self.bundle), "--dry-run", workspace=restored)
        self.assertTrue(preview["dry_run"])
        self.assertFalse(preview["restored"])
        self.assertFalse(restored.exists())
        result = self.json_command("restore", "--input", str(self.bundle), workspace=restored)
        self.assertTrue(result["restored"])
        self.assertFalse(result["dry_run"])
        self.assertEqual(self.personal_state(restored), expected)
        self.assertEqual((restored / "Notes/保留的手写说明.md").read_bytes(), note.read_bytes())
        self.json_command("build", workspace=restored)
        self.assertTrue(self.json_command("search", "园艺", workspace=restored))
        review = self.json_command("review", workspace=restored)
        self.assertEqual(next(task["outcome"] for task in review["completed_tasks"] if task["id"] == identifier), outcome)
        self.assertIn(outcome, (restored / "Review.md").read_text(encoding="utf-8"))
        before = self.hashes(restored)
        code, _, errors = self.invoke("restore", "--input", str(self.bundle), workspace=restored)
        self.assertEqual(code, 1)
        self.assertTrue(errors)
        self.assertEqual(self.hashes(restored), before)
        self.model.assert_not_called()
        self.network.assert_not_called()
        self.remote.assert_not_called()

    def test_invalid_zip_dry_run_never_creates_destination(self):
        self.bundle.write_bytes(b"not a backup zip")
        destination = self.base / "invalid-restore"
        code, _, errors = self.invoke("restore", "--input", str(self.bundle), "--dry-run", workspace=destination)
        self.assertEqual(code, 1)
        self.assertTrue(errors)
        self.assertFalse(destination.exists())

    def test_tampered_payload_dry_run_never_creates_destination(self):
        self.json_command("backup", "--output", str(self.bundle))
        tampered = self.base / "tampered.zip"
        with zipfile.ZipFile(self.bundle) as original:
            members = [(item, original.read(item)) for item in original.infolist()]
        victim = next(item.filename for item, _ in members if item.filename.endswith(".md"))
        with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for item, data in members:
                output.writestr(item, data + b"\nchanged fixture\n" if item.filename == victim else data)
        destination = self.base / "tampered-restore"
        code, _, errors = self.invoke("restore", "--input", str(tampered), "--dry-run", workspace=destination)
        self.assertEqual(code, 1)
        self.assertTrue(errors)
        self.assertFalse(destination.exists())

    def test_initial_status_does_not_claim_a_successful_sync(self):
        fresh = self.base / "not-yet-run"
        self.json_command("init", workspace=fresh)
        status = self.json_command("status", workspace=fresh)
        self.assertIsNone(status["last_run"])
        self.assertIsNone(status["last_attempt"])
        self.assertIn("sources", status)
        self.assertIn("engine", status)

    def test_failed_sync_exposes_latest_failure_and_preserves_last_success(self):
        successful = self.json_command("status")["last_run"]
        marker = "UNPUBLISHED_PERSONAL_NOTE_MARKER"
        with (self.root / "Home.md").open("a", encoding="utf-8") as output:
            output.write("\n" + marker + "\n")
        code, _, errors = self.invoke("sync")
        self.assertEqual(code, 1)
        self.assertTrue(errors)
        status = self.json_command("status")
        self.assertEqual(status["last_run"], successful)
        attempt = status["last_attempt"]
        self.assertEqual(attempt["status"], "failed")
        self.assertTrue(attempt["phase"])
        self.assertTrue(attempt["error"])
        self.assertTrue(attempt["next_step"])
        self.assertTrue(attempt["saved"]["catalog"])
        self.assertFalse(attempt["saved"]["rendered"])
        self.assertNotIn(marker, json.dumps(attempt))
        code, text, errors = self.invoke("status", "--format", "text")
        self.assertEqual(code, 0, errors)
        self.assertTrue("failed" in text.lower() or "失败" in text)
        self.assertIn(marker, (self.root / "Home.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
