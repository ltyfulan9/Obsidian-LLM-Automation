"""A new user can verify the product without real sources, models or network."""

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from knowledge.catalog import Catalog
from knowledge.cli import main


class OnboardingCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="knowledge-onboarding-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "demo"
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.model = stack.enter_context(patch("knowledge.summarize.invoke_cli", side_effect=AssertionError("Demo must not call a model")))
        self.network = stack.enter_context(patch("urllib.request.urlopen", side_effect=AssertionError("Demo must not fetch a source")))
        stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Demo must stay offline")))
        self.remote = stack.enter_context(patch("knowledge.publish.private_target", side_effect=AssertionError("No implicit publication check")))

    def invoke(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main([arguments[0], "--workspace", str(self.root), *arguments[1:]])
        return code, output.getvalue(), errors.getvalue()

    def test_new_user_completes_offline_demo_diagnosis_and_search(self):
        code, output, errors = self.invoke("demo")
        self.assertEqual(code, 0, errors)
        result = json.loads(output)
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["documents"], 2)
        self.assertEqual(Path(result["workspace"]), self.root)
        self.assertEqual(Path(result["home"]), self.root / "Home.md")
        self.assertTrue(result["next_steps"])
        for name in ("Home.md", "Timeline.md", "Tasks.md", "Review.md"):
            self.assertTrue((self.root / name).is_file(), name)
        self.assertTrue(list((self.root / "Notes").glob("*.md")), "A handwritten guide should explain the next step")
        catalog = Catalog(self.root)
        try:
            self.assertEqual(len(catalog.rows()), 2)
            personal = catalog.personal_state()
            self.assertEqual(len(personal["tasks"]), 1)
            self.assertEqual(personal["tasks"][0]["id"], result["task_id"])
            self.assertEqual(len(personal["checkins"]), 1)
        finally:
            catalog.close()
        code, _, errors = self.invoke("doctor")
        self.assertEqual(code, 0, errors)
        code, output, errors = self.invoke("doctor", "--format", "json")
        self.assertEqual(code, 0, errors)
        self.assertIsInstance(json.loads(output), dict)
        code, output, errors = self.invoke("search", "园艺")
        self.assertEqual(code, 0, errors)
        hits = json.loads(output)
        self.assertTrue(hits)
        self.assertTrue(any(hit["file"].startswith("Sources/") for hit in hits))
        self.model.assert_not_called()
        self.network.assert_not_called()
        self.remote.assert_not_called()

    def test_repeating_demo_never_resets_existing_knowledge(self):
        code, _, errors = self.invoke("demo")
        self.assertEqual(code, 0, errors)
        note = self.root / "Notes/my-observation.md"
        note.write_text("我的手写内容，必须保留。", encoding="utf-8")
        before = {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in self.root.rglob("*") if path.is_file()}
        code, _, _ = self.invoke("demo")
        self.assertEqual(code, 1)
        after = {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_doctor_reports_missing_workspace_without_creating_it(self):
        code, output, _ = self.invoke("doctor", "--format", "json")
        self.assertEqual(code, 1)
        self.assertIsInstance(json.loads(output), dict)
        self.assertFalse(self.root.exists())
        self.model.assert_not_called()
        self.network.assert_not_called()
        self.remote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
