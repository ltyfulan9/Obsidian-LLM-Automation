import gzip
import json
import random
import string
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from knowledge.common import KnowledgeError, atomic_write, workspace_lock
from knowledge.ingest import Document
from knowledge.magpie import export_bundle, verify_target
from knowledge.process import run as run_process
from knowledge.projection_store import commit, recover, registry
from knowledge.service import initialize
from knowledge.summarize import TransientSummaryError, summarize


class ReliabilityCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="knowledge-reliability-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "wiki"
        initialize(self.root)

    def test_os_lock_blocks_overlap_and_releases_after_exit(self):
        with workspace_lock(self.root):
            with self.assertRaisesRegex(KnowledgeError, "holds"):
                with workspace_lock(self.root):
                    self.fail("A second writer acquired the workspace")
        with workspace_lock(self.root):
            pass
        # File persistence is intentional; it does not represent a live lock.
        self.assertTrue((self.root / ".knowledge/run.lock").exists())

    def test_interrupted_generation_recovers_without_model_calls(self):
        original = atomic_write
        calls = 0

        def interrupted(path, text):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("Synthetic power interruption")
            original(path, text)

        desired = {"Home.md": "Updated home\n", "Timeline.md": "Updated dates\n"}
        with patch("knowledge.projection_store.atomic_write", side_effect=interrupted):
            with self.assertRaises(OSError):
                commit(self.root, desired)
        self.assertTrue((self.root / ".knowledge/render-journal.json").exists())
        recover(self.root)
        self.assertEqual((self.root / "Home.md").read_text(), "Updated home\n")
        self.assertEqual((self.root / "Timeline.md").read_text(), "Updated dates\n")
        self.assertEqual(set(registry(self.root)), set(desired))
        self.assertFalse((self.root / ".knowledge/render-journal.json").exists())

    def test_recovery_preserves_manual_edit_after_interruption(self):
        with patch("knowledge.projection_store.atomic_write", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                commit(self.root, {"Home.md": "New home\n"})
        (self.root / "Home.md").write_text("Handwritten rescue\n")
        with self.assertRaisesRegex(KnowledgeError, "Manual edit"):
            recover(self.root)
        self.assertEqual((self.root / "Home.md").read_text(), "Handwritten rescue\n")

    def test_registry_cannot_remove_handwritten_files(self):
        with self.assertRaises(KnowledgeError):
            commit(self.root, {"Notes/private.md": "Unexpected content"})

    def test_successful_chunks_survive_later_provider_failure(self):
        document = Document("fixture", "synthetic", "chat", "codex", "2026-01-01", "Synthetic", "a" * 2000 + "b" * 2000, [])
        value = {"title": "Synthetic", "summary": "Summary", "topics": ["Testing"], "key_points": [], "decisions": [], "questions": []}
        engine = {"name": "claude", "chunk_chars": 2000, "retries": 0, "cache_dir": str(self.root / ".knowledge/summary-cache")}
        with patch("knowledge.summarize.invoke_cli", side_effect=[value, KnowledgeError("provider unavailable")]):
            with self.assertRaises(KnowledgeError):
                summarize(document, engine, {})
        with patch("knowledge.summarize.invoke_cli", return_value=value) as model:
            summarize(document, engine, {})
        self.assertEqual(model.call_count, 2)  # second chunk and merge; first chunk reused

    def test_transient_retry_is_bounded(self):
        document = Document("fixture", "synthetic", "chat", "codex", "2026-01-01", "Synthetic", "short text", [])
        value = {"title": "Synthetic", "summary": "Summary", "topics": [], "key_points": [], "decisions": [], "questions": []}
        with patch("knowledge.summarize.invoke_cli", side_effect=[TransientSummaryError("timeout"), value]) as model, patch("knowledge.summarize.time.sleep"):
            summarize(document, {"name": "claude", "retries": 1}, {})
        self.assertEqual(model.call_count, 2)

    def test_provider_process_timeout_is_enforced(self):
        import subprocess
        with self.assertRaises(subprocess.TimeoutExpired):
            run_process([sys.executable, "-c", "import time; time.sleep(10)"], input="", cwd=self.root, timeout=0.2)


class MagpieBundleCase(unittest.TestCase):
    def row(self, identity, kind="claude", text="A synthetic reusable summary"):
        return {"document": {"id": identity, "kind": kind, "day": "2026-11-08"},
                "summary": {"title": "Synthetic conversation", "summary": text, "topics": ["Testing"],
                            "key_points": ["A point"], "decisions": ["A choice"], "questions": ["An open question"], "method": "claude"}}

    def export(self, rows, output, max_kib=64):
        with patch("knowledge.magpie.datetime") as clock:
            clock.now.return_value = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
            return export_bundle(rows, output, {"timezone": "+08:00", "magpie": {"keep_days": 7, "max_kib": max_kib}})

    def test_export_is_small_deterministic_and_has_no_raw_transcript(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            rows = [self.row("one"), self.row("note", kind="markdown")]
            first = self.export(rows, path)
            data = (path / "conversations.json.gz").read_bytes()
            second = self.export(rows, path)
            self.assertEqual(data, (path / "conversations.json.gz").read_bytes())
            value = json.loads(gzip.decompress(data))
            self.assertEqual(len(value["records"]), 1)
            self.assertNotIn("text", value["records"][0])
            self.assertFalse(first["full_transcripts"])
            self.assertEqual(first, second)
            self.assertLessEqual(len(data), 64 * 1024)

    def test_budget_omissions_are_reported(self):
        randomizer = random.Random(0)
        rows = [self.row(str(i), text="".join(randomizer.choices(string.ascii_letters, k=600))) for i in range(120)]
        with tempfile.TemporaryDirectory() as folder:
            result = self.export(rows, Path(folder), max_kib=4)
            self.assertLessEqual(result["gzip_bytes"], 4096)
            self.assertGreater(result["omitted_for_budget"], 0)
            self.assertEqual(result["included"] + result["omitted_for_budget"], len(rows))

    def test_public_magpie_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "sync.json").write_text(json.dumps({"url": "github://example/public", "library": True}))
            config = {"magpie": {"executable": "synthetic-magpie", "data_dir": folder}}
            with patch("knowledge.publish.run", return_value="false"), patch("knowledge.magpie.shutil.which", return_value="synthetic"):
                with self.assertRaisesRegex(KnowledgeError, "private"):
                    verify_target(config)

    def test_unregistered_package_does_not_claim_to_be_synced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "sync.json").write_text(json.dumps({"url": "github://example/private", "library": True}))
            (path / "library.json").write_text(json.dumps({"skills": []}))
            config = {"magpie": {"executable": "synthetic-magpie", "data_dir": folder}}
            with patch("knowledge.publish.run", return_value="true"), patch("knowledge.magpie.shutil.which", return_value="synthetic"):
                with self.assertRaisesRegex(KnowledgeError, "Import"):
                    verify_target(config)


if __name__ == "__main__":
    unittest.main()
