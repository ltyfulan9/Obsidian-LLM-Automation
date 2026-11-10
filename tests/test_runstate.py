"""Failures must not disguise themselves as an old success or expose source text."""

import hashlib
import json
import unittest
from unittest.mock import patch

from test_knowledge import WorkspaceFixture
from knowledge.common import KnowledgeError, workspace_lock, write_json
from knowledge.runstate import RunAttempt, append_log, status
from knowledge.service import sync


class RunStateCase(WorkspaceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.note()
        self.configure()

    def hashes(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*") if p.is_file()}

    def test_success_and_readonly_status(self):
        result = sync(self.root)
        before = self.hashes()
        value = status(self.root)
        self.assertEqual(value["last_run"], result)
        self.assertEqual(value["last_attempt"]["status"], "succeeded")
        self.assertEqual(value["last_attempt"]["saved"], {"catalog": True, "rendered": True, "published": False, "magpie": False})
        self.assertFalse(value["workspace_busy"])
        self.assertEqual(self.hashes(), before)

    def test_missing_source_retains_last_success(self):
        previous = sync(self.root)
        self.source.rename(self.base / "disconnected")
        with self.assertRaises(KnowledgeError):
            sync(self.root)
        value = status(self.root)
        self.assertEqual(value["last_run"], previous)
        self.assertEqual(value["last_attempt"]["phase"], "collect")
        self.assertEqual(value["last_attempt"]["error"], "collect_failed")
        self.assertFalse(value["last_attempt"]["saved"]["catalog"])

    def test_provider_error_body_never_enters_run_state_or_log(self):
        self.config["engine"]["name"] = "codex"
        write_json(self.root / ".knowledge/config.json", self.config)
        marker = "INVENTED_PRIVATE_ERROR_BODY"
        with patch("knowledge.service.summarize", side_effect=KnowledgeError(marker)):
            with self.assertRaises(KnowledgeError):
                sync(self.root)
        append_log(self.root)
        for name in ("run-state.json", "scheduler.jsonl"):
            self.assertNotIn(marker, (self.root / ".knowledge" / name).read_text(encoding="utf-8"))
        self.assertEqual(status(self.root)["last_attempt"]["error"], "summarize_failed")

    def test_render_and_publish_failures_report_confirmed_saves(self):
        for phase, dependency in (("render", "build"), ("publish", "publish")):
            with self.subTest(phase=phase), patch("knowledge.service." + dependency, side_effect=KnowledgeError("invented failure")), \
                    patch("knowledge.service.private_target", return_value="invented/private"):
                with self.assertRaises(KnowledgeError):
                    sync(self.root, push=phase == "publish")
                latest = status(self.root)["last_attempt"]
                self.assertEqual(latest["phase"], phase)
                self.assertTrue(latest["saved"]["catalog"])
                self.assertEqual(latest["saved"]["rendered"], phase == "publish")
                self.assertFalse(latest["saved"]["published"])

    def test_invalid_configuration_still_records_failure(self):
        previous = sync(self.root)
        write_json(self.root / ".knowledge/config.json", {"version": "invalid"})
        with self.assertRaises(KnowledgeError):
            sync(self.root)
        value = status(self.root)
        self.assertTrue(value["configuration_error"])
        self.assertEqual(value["last_attempt"]["phase"], "configuration")
        self.assertEqual(value["last_run"], previous)

    def test_released_lock_turns_running_record_into_interrupted_without_writes(self):
        RunAttempt(self.root, False, False)
        before = self.hashes()
        latest = status(self.root)["last_attempt"]
        self.assertEqual(latest["status"], "interrupted")
        self.assertEqual(latest["recorded_status"], "running")
        self.assertEqual(self.hashes(), before)

    def test_actual_held_lock_keeps_running_and_status_does_not_unlock_it(self):
        with workspace_lock(self.root):
            RunAttempt(self.root, False, False)
            value = status(self.root)
            self.assertTrue(value["workspace_busy"])
            self.assertEqual(value["last_attempt"]["status"], "running")
            with self.assertRaises(KnowledgeError):
                with workspace_lock(self.root):
                    self.fail("Status released another command's lock")

    def test_corrupt_attempt_shape_is_refused_and_next_step_is_not_trusted(self):
        run = RunAttempt(self.root, False, False)
        run.finish(failed=True)
        path = self.root / ".knowledge/run-state.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["last_attempt"]["next_step"] = "UNTRUSTED_ACTION_MARKER"
        write_json(path, data)
        self.assertNotIn("UNTRUSTED_ACTION_MARKER", json.dumps(status(self.root)))
        for bad in (None, [], "invalid"):
            data["last_attempt"]["saved"] = bad
            write_json(path, data)
            before = path.read_bytes()
            with self.assertRaises(KnowledgeError):
                status(self.root)
            self.assertEqual(path.read_bytes(), before)
