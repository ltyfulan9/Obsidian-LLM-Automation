"""Do not feed generated projections or internal agent sessions back into knowledge."""

import unittest

from test_knowledge import WorkspaceFixture
from knowledge.common import KnowledgeError
from knowledge.ingest import native_messages, read_source


class BoundaryCase(WorkspaceFixture, unittest.TestCase):
    def test_generated_directory_cannot_be_a_source(self):
        path = self.root / "Wiki"
        path.mkdir(exist_ok=True)
        (path / "synthetic.md").write_text("# Invented generated page", encoding="utf-8")
        with self.assertRaisesRegex(KnowledgeError, "generated"):
            read_source({"name": "bad", "kind": "markdown", "path": str(path)}, self.config, self.root)

    def test_handwritten_notes_inside_workspace_are_valid(self):
        path = self.root / "Notes"
        (path / "synthetic.md").write_text("# Invented handwritten observation", encoding="utf-8")
        rows = read_source({"name": "handwritten", "kind": "markdown", "path": str(path)}, self.config, self.root)
        self.assertTrue(any(row.title == "Invented handwritten observation" for row in rows))

    def test_generated_root_page_cannot_be_a_source(self):
        with self.assertRaisesRegex(KnowledgeError, "generated"):
            read_source({"name": "bad", "kind": "markdown", "path": str(self.root / "Home.md")}, self.config, self.root)

    def test_codex_subagent_metadata_is_excluded_without_path_conventions(self):
        message = {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "Invented internal agent task"}}
        for source in ("subagent", {"subagent": {}}):
            records = [{"type": "session_meta", "payload": {"source": source}}, message]
            self.assertEqual(native_messages(records, "codex"), [])
        self.assertEqual(len(native_messages([{"type": "session_meta", "payload": {"source": "vscode"}}, message], "codex")), 1)

    def test_hidden_analysis_channel_is_excluded(self):
        records = [{"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": channel,
                    "content": text}} for channel, text in (("analysis", "internal"), ("final", "visible"))]
        self.assertEqual(native_messages(records, "codex"), [("assistant", "visible", None)])
