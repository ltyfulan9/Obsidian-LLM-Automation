"""Synthetic state packages exercise complete recovery and hostile ZIP rejection."""

import hashlib
import json
import os
import sqlite3
import stat
import unittest
import warnings
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from test_knowledge import WorkspaceFixture
from knowledge.backup import backup, restore
from knowledge.catalog import Catalog
from knowledge.common import KnowledgeError
from knowledge.reflection import checkin, task
from knowledge.service import rebuild, sync
from knowledge import projection_store


class BackupCase(WorkspaceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.note(body="# Invented recovery evidence\n\nAn observation with a recorded result.")
        removed = self.note("2026-01-03-removed.md", "# Invented older evidence\n\nRetain historical availability.")
        self.configure()
        sync(self.root)
        removed.unlink()
        sync(self.root)
        checkin(self.root, "2026-01-04", ["Invented progress"], ["Invented dependency"], ["Check prerequisites"])
        identifier = task(self.root, "add", "Invented deliverable", day="2026-01-04", due="2026-01-05", expected="One verified sample")["id"]
        task(self.root, "defer", identifier, day="2026-01-05", due="2026-01-07", reason="Invented dependency delayed")
        task(self.root, "finish", identifier, day="2026-01-07", outcome="Invented sample accepted")
        self.note_file = self.root / "Notes/含 空格/原样.bin"
        self.note_file.parent.mkdir()
        self.note_file.write_bytes(b"invented\x00binary\r\n" + bytes(range(256)))
        os.utime(self.note_file, ns=(1700000000123456000, 1700000000123456000))
        self.bundle = self.base / "private-state.zip"

    def state(self, root):
        catalog = Catalog(root)
        try:
            return (catalog.rows(), catalog.personal_state(), [tuple(row) for row in catalog.connection.execute(
                "SELECT id,content_hash,engine_hash,available FROM documents ORDER BY id")])
        finally:
            catalog.close()

    def package(self):
        return backup(self.root, self.bundle)

    def rewrite(self, *, additions=(), change_manifest=None, replace=None, compression=zipfile.ZIP_DEFLATED):
        if not self.bundle.exists():
            self.package()
        with zipfile.ZipFile(self.bundle) as original:
            files = {info.filename: original.read(info) for info in original.infolist()}
        if change_manifest:
            value = json.loads(files["manifest.json"])
            change_manifest(value)
            files["manifest.json"] = json.dumps(value, ensure_ascii=False).encode("utf-8")
        if replace:
            files.update(replace)
        destination = self.base / "modified.zip"
        with warnings.catch_warnings(), zipfile.ZipFile(destination, "w", compression=compression) as output:
            warnings.simplefilter("ignore", UserWarning)
            for name, content in files.items():
                output.writestr(name, content)
            for item, content in additions:
                output.writestr(item, content)
        return destination

    def assert_rejected(self, package):
        target = self.base / "must-not-exist/nested/wiki"
        with self.assertRaises(KnowledgeError):
            restore(package, target)
        self.assertFalse(target.exists())
        self.assertFalse((self.base / "must-not-exist").exists())

    def test_roundtrip_preserves_personal_history_notes_availability_and_incremental_hashes(self):
        expected = self.state(self.root)
        result = self.package()
        self.assertEqual(Path(result["backup"]).resolve(), self.bundle.resolve())
        self.assertTrue(result["private_state"])
        self.assertFalse(result["source_attachments"])
        self.assertGreater(result["files"], 4)
        self.assertEqual(result["bytes"], self.bundle.stat().st_size)
        target = self.base / "恢复 知识库"
        restored = restore(self.bundle, target)
        self.assertEqual(Path(restored["workspace"]).resolve(), target.resolve())
        self.assertTrue(restored["restored"])
        self.assertFalse(restored["dry_run"])
        self.assertEqual(self.state(target), expected)
        note = target / self.note_file.relative_to(self.root)
        self.assertEqual(note.read_bytes(), self.note_file.read_bytes())
        self.assertEqual(note.stat().st_mtime_ns, self.note_file.stat().st_mtime_ns)
        with patch("knowledge.service.summarize") as model:
            rebuild(target)
            run = sync(target)
        model.assert_not_called()
        self.assertEqual((run["updated"], run["unchanged"]), (0, 1))
        self.assertEqual(self.state(target), expected)

    def test_backup_and_dry_run_do_not_read_external_sources_or_call_services(self):
        original_open = Path.open

        def opened(path, *args, **kwargs):
            if path.is_relative_to(self.source):
                self.fail("State packaging must not open external source content")
            return original_open(path, *args, **kwargs)

        with patch("pathlib.Path.open", opened), patch("knowledge.service.read_source") as reader, \
                patch("knowledge.summarize.invoke_cli") as model, \
                patch("socket.create_connection", side_effect=AssertionError("No network during recovery")):
            self.package()
            target = self.base / "new-parent/new-workspace"
            result = restore(self.bundle, target, dry_run=True)
        self.assertFalse(result["restored"])
        self.assertTrue(result["dry_run"])
        self.assertFalse(target.parent.exists())
        reader.assert_not_called()
        model.assert_not_called()

    def test_scope_contains_owned_state_but_not_git_authentication_or_deployment_scripts(self):
        for name in (".git/config", ".codex/auth.json", "automation/private-deployment.py", ".knowledge/deployment.json"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"invented excluded material")
        self.package()
        with zipfile.ZipFile(self.bundle) as package:
            names = package.namelist()
            manifest = json.loads(package.read("manifest.json"))
        self.assertTrue(manifest["private"])
        self.assertEqual(set(manifest["files"]), set(names) - {"manifest.json"})
        self.assertNotIn(".git/config", names)
        self.assertNotIn(".codex/auth.json", names)
        self.assertNotIn("automation/private-deployment.py", names)
        self.assertNotIn(".knowledge/deployment.json", names)

    def test_existing_output_destination_and_workspace_output_are_never_overwritten(self):
        self.bundle.write_bytes(b"Keep an existing backup")
        with self.assertRaises(KnowledgeError):
            self.package()
        self.assertEqual(self.bundle.read_bytes(), b"Keep an existing backup")
        with self.assertRaises(KnowledgeError):
            backup(self.root, self.root / "unsafe.zip")
        with self.assertRaises(KnowledgeError):
            backup(self.root, Path(__file__).resolve().parent.parent / "unsafe-state.zip")

    def test_restore_existing_workspace_leaves_every_existing_byte_untouched(self):
        self.package()
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with self.assertRaises(KnowledgeError):
            restore(self.bundle, self.root)
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_manually_edited_generated_page_is_saved_with_its_edit_protection(self):
        page = self.root / "Home.md"
        page.write_bytes(page.read_bytes() + b"\nKeep invented manual edit\n")
        self.package()
        target = self.base / "manual-edit-restored"
        restore(self.bundle, target)
        self.assertEqual((target / "Home.md").read_bytes(), page.read_bytes())
        with self.assertRaisesRegex(KnowledgeError, "manual changes"):
            rebuild(target)

    def interrupted_generation(self):
        self.note("2026-01-08-new.md", "# New invented observation\n\nA new result after the earlier snapshot.")
        original = projection_store.atomic_write
        count = 0
        def interrupted(path, text):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("invented interrupted generation")
            original(path, text)
        with patch("knowledge.projection_store.atomic_write", side_effect=interrupted), self.assertRaises(OSError):
            sync(self.root)
        journal = self.root / ".knowledge/render-journal.json"
        self.assertTrue(journal.is_file())
        return json.loads(journal.read_text(encoding="utf-8"))

    def test_interrupted_generation_roundtrips_and_build_recovers_without_model_calls(self):
        self.interrupted_generation()
        expected = self.state(self.root)
        result = self.package()
        self.assertTrue(result["pending_recovery"])
        target = self.base / "interrupted-restored"
        restored = restore(self.bundle, target)
        self.assertTrue(restored["pending_recovery"])
        self.assertTrue((target / ".knowledge/render-journal.json").is_file(), "Restore must not execute the journal")
        with patch("knowledge.service.summarize") as model:
            rebuild(target)
        model.assert_not_called()
        self.assertFalse((target / ".knowledge/render-journal.json").exists())
        self.assertEqual(self.state(target), expected)
        self.assertTrue(any("New invented observation" in page.read_text(encoding="utf-8") for page in (target / "Sources").glob("*.md")))

    def test_edits_to_unregistered_new_pages_survive_pending_journal_backup(self):
        journal = self.interrupted_generation()
        previous = json.loads((self.root / ".knowledge/generated.json").read_text(encoding="utf-8"))
        fresh = next(name for name in journal["writes"] if name not in previous and (self.root / name).is_file())
        page = self.root / fresh
        page.write_bytes(page.read_bytes() + b"\nPreserve invented handwritten rescue\n")
        expected = page.read_bytes()
        self.package()
        target = self.base / "rescue-restored"
        restore(self.bundle, target)
        self.assertEqual((target / fresh).read_bytes(), expected)
        with self.assertRaisesRegex(KnowledgeError, "Manual edit"):
            rebuild(target)
        self.assertEqual((target / fresh).read_bytes(), expected)

    def test_unsafe_names_links_and_directory_entries_are_rejected_before_destination_creation(self):
        self.package()
        for name in ("../escape.md", "/absolute.md", "C:/drive.md", "Notes\\escape.md", ".", "Notes/a/../escape.md", "Notes/a:stream", "Notes/CON.txt"):
            info = zipfile.ZipInfo("temporary")
            info.filename = name  # Preserve hostile central-directory bytes even on Windows.
            with self.subTest(name=name):
                self.assert_rejected(self.rewrite(additions=[(info, b"invented")]))
        link = zipfile.ZipInfo("Notes/link.md")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assert_rejected(self.rewrite(additions=[(link, b"../../outside")]))
        self.assert_rejected(self.rewrite(additions=[("Notes/directory/", b"")]))

    def test_duplicate_case_unicode_and_file_directory_collisions_are_rejected(self):
        self.package()
        for names in (("Home.md",), ("Notes/Case.md", "Notes/case.md"),
                      ("Notes/é.md", "Notes/e\u0301.md"), ("Notes/item", "Notes/item/part.md")):
            with self.subTest(names=names):
                self.assert_rejected(self.rewrite(additions=[(name, b"invented") for name in names]))

    def test_bad_checksums_missing_files_unknown_versions_and_invalid_zips_are_rejected(self):
        self.package()
        def bad_checksum(manifest):
            next(iter(manifest["files"].values()))["sha256"] = "0" * 64
        self.assert_rejected(self.rewrite(change_manifest=bad_checksum))
        self.assert_rejected(self.rewrite(change_manifest=lambda manifest: manifest.update(version=999)))
        self.assert_rejected(self.rewrite(change_manifest=lambda manifest: manifest["files"].pop(".knowledge/config.json")))
        broken = self.base / "broken.zip"
        broken.write_bytes(b"not a zip")
        self.assert_rejected(broken)

    def test_expanded_file_count_and_size_limits_are_enforced(self):
        self.package()
        for field, maximum in (("MAX_FILES", 1), ("MAX_FILE_BYTES", 16), ("MAX_TOTAL_BYTES", 64), ("MAX_MANIFEST_BYTES", 8)):
            with self.subTest(field=field), patch("knowledge.backup." + field, maximum):
                self.assert_rejected(self.bundle)

    def test_authentication_files_inside_notes_are_not_silently_packaged(self):
        (self.root / "Notes/auth.json").write_bytes(b"invented authentication material")
        with self.assertRaises(KnowledgeError):
            self.package()
        self.assertFalse(self.bundle.exists())

    def test_corrupt_snapshot_database_is_rejected_even_with_matching_file_checksum(self):
        self.package()
        content = b"invented corrupt database"
        def corrupt(manifest):
            manifest["files"][".knowledge/catalog.sqlite3"].update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
        self.assert_rejected(self.rewrite(change_manifest=corrupt, replace={".knowledge/catalog.sqlite3": content}))

    def test_missing_empty_and_corrupt_catalogs_are_not_recreated_by_normal_open(self):
        path = self.root / ".knowledge/catalog.sqlite3"
        path.unlink()
        with self.assertRaises(KnowledgeError):
            Catalog(self.root)
        self.assertFalse(path.exists())
        for value in (b"", b"invented broken sqlite"):
            path.write_bytes(value)
            with self.subTest(value=value), self.assertRaises(KnowledgeError):
                Catalog(self.root)
            self.assertEqual(path.read_bytes(), value)

    def test_invalid_existing_schema_is_rejected_before_any_compatible_upgrade(self):
        path = self.root / ".knowledge/catalog.sqlite3"
        with closing(sqlite3.connect(path)) as database, database:
            database.execute("DROP TABLE documents")
            database.execute("CREATE TABLE documents (id TEXT)")
        before = path.read_bytes()
        with self.assertRaises(KnowledgeError):
            Catalog(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_extra_column_is_rejected_before_an_expensive_sync_can_reach_insert(self):
        path = self.root / ".knowledge/catalog.sqlite3"
        with closing(sqlite3.connect(path)) as database, database:
            database.execute("ALTER TABLE documents ADD COLUMN unsupported TEXT")
        before = path.read_bytes()
        with self.assertRaises(KnowledgeError):
            Catalog(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_missing_primary_key_is_rejected_without_changing_existing_database(self):
        path = self.root / ".knowledge/catalog.sqlite3"
        with closing(sqlite3.connect(path)) as database, database:
            sql = database.execute("SELECT sql FROM sqlite_master WHERE name='documents'").fetchone()[0]
            database.execute("DROP TABLE documents")
            database.execute(sql.replace("id TEXT PRIMARY KEY", "id TEXT"))
        before = path.read_bytes()
        with self.assertRaises(KnowledgeError):
            Catalog(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_reordered_columns_cannot_silently_change_positional_inserts(self):
        path = self.root / ".knowledge/catalog.sqlite3"
        with closing(sqlite3.connect(path)) as database, database:
            sql = database.execute("SELECT sql FROM sqlite_master WHERE name='documents'").fetchone()[0]
            modified = sql.replace("source TEXT NOT NULL, day TEXT NOT NULL", "day TEXT NOT NULL, source TEXT NOT NULL")
            self.assertNotEqual(sql, modified)
            database.execute("DROP TABLE documents")
            database.execute(modified)
        before = path.read_bytes()
        with self.assertRaises(KnowledgeError):
            Catalog(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_owned_table_trigger_is_rejected_before_it_can_delete_personal_records(self):
        path = self.root / ".knowledge/catalog.sqlite3"
        with closing(sqlite3.connect(path)) as database, database:
            database.execute("""CREATE TRIGGER invented_unsupported_trigger AFTER INSERT ON documents
                                BEGIN DELETE FROM commitments; DELETE FROM commitment_events; END""")
        before = path.read_bytes()
        self.note("2026-01-08-new.md", "# New invented evidence\n\nMust not execute the trigger.")
        with patch("knowledge.service.summarize") as model, self.assertRaises(KnowledgeError):
            sync(self.root)
        model.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
            self.assertEqual(database.execute("SELECT count(*) FROM commitments").fetchone()[0], 1)
            self.assertEqual(database.execute("SELECT count(*) FROM commitment_events").fetchone()[0], 3)
