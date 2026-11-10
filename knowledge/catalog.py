"""Transactional catalog; generated Markdown is a rebuildable projection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .common import KnowledgeError


TABLE_COLUMNS = {
    "documents": ("id", "source", "day", "content_hash", "engine_hash", "document", "summary", "available"),
    "checkins": ("day", "data"),
    "commitments": ("id", "title", "created", "expected", "source_id"),
    "commitment_events": ("seq", "task_id", "day", "kind", "data"),
}
TABLE_KEYS = {"documents": "id", "checkins": "day", "commitments": "id", "commitment_events": "seq"}


def validate_schema(connection: sqlite3.Connection) -> None:
    """Inspect the existing schema before any compatible table upgrade writes."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "documents" not in tables:
        raise KnowledgeError("Catalog schema is missing; keep existing files and restore a verified state backup")
    triggers = [row[0] for row in connection.execute("SELECT tbl_name FROM sqlite_master WHERE type='trigger'")]
    if any(not isinstance(table, str) or table.casefold() in TABLE_COLUMNS for table in triggers):
        raise KnowledgeError("Catalog contains unsupported triggers on owned tables; keep existing files and restore a verified state backup")
    for table, required in TABLE_COLUMNS.items():
        if table not in tables:
            continue
        columns = list(connection.execute(f"PRAGMA table_info({table})"))
        keys = {row[1]: row[5] for row in columns if row[5]}
        invalid_types = any(row[2].upper() != ("INTEGER" if (table, row[1]) in {("documents", "available"), ("commitment_events", "seq")} else "TEXT")
                            for row in columns)
        if tuple(row[1] for row in columns) != required or keys != {TABLE_KEYS[table]: 1} or invalid_types:
            raise KnowledgeError("Catalog schema is invalid; keep existing files and restore a verified state backup")


class Catalog:
    def __init__(self, root: Path, create: bool = False):
        path = (root / ".knowledge/catalog.sqlite3").resolve()
        self.connection = None
        try:
            mode = "rwc" if create else "rw"
            self.connection = sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True)
            if not create:
                validate_schema(self.connection)
            self.connection.row_factory = sqlite3.Row
            self._initialize_tables()
        except (sqlite3.Error, KnowledgeError) as exc:
            if self.connection is not None:
                self.connection.close()
            raise KnowledgeError("Catalog is missing or invalid; run knowledge doctor and restore a verified state backup. Existing files were kept.") from exc

    def _initialize_tables(self) -> None:
        self.connection.execute("""CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, day TEXT NOT NULL,
            content_hash TEXT NOT NULL, engine_hash TEXT NOT NULL,
            document TEXT NOT NULL, summary TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1
        )""")
        self.connection.execute("CREATE TABLE IF NOT EXISTS checkins (day TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS commitments (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL,
            expected TEXT NOT NULL, source_id TEXT
        )""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS commitment_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
            day TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL
        )""")
        self.connection.commit()

    def close(self):
        self.connection.close()

    def current(self, document_id: str):
        return self.connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()

    def save(self, document: dict, summary: dict, content_hash: str, engine_hash: str):
        self.connection.execute("""INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET source=excluded.source, day=excluded.day,
            content_hash=excluded.content_hash, engine_hash=excluded.engine_hash,
            document=excluded.document, summary=excluded.summary, available=1""",
            (document["id"], document["source"], document["day"], content_hash, engine_hash,
             json.dumps(document, ensure_ascii=False), json.dumps(summary, ensure_ascii=False)))

    def mark_missing(self, source: str, present: set[str]):
        for row in self.connection.execute("SELECT id FROM documents WHERE source = ?", (source,)).fetchall():
            self.connection.execute("UPDATE documents SET available = ? WHERE id = ?", (int(row["id"] in present), row["id"]))

    def rows(self) -> list[dict]:
        return [{"document": json.loads(row["document"]), "summary": json.loads(row["summary"]),
                 "available": bool(row["available"])} for row in self.connection.execute("SELECT * FROM documents ORDER BY day DESC, id")]

    def personal_state(self) -> dict:
        # All three reads must observe the same snapshot, including during a CLI search.
        own_transaction = not self.connection.in_transaction
        if own_transaction:
            self.connection.execute("BEGIN")
        try:
            return {
                "checkins": [{"day": row["day"], **json.loads(row["data"])} for row in self.connection.execute("SELECT * FROM checkins ORDER BY day")],
                "tasks": [dict(row) for row in self.connection.execute("SELECT * FROM commitments ORDER BY created, id")],
                "events": [{"seq": row["seq"], "task_id": row["task_id"], "day": row["day"], "kind": row["kind"],
                            **json.loads(row["data"])} for row in self.connection.execute("SELECT * FROM commitment_events ORDER BY day, seq")],
            }
        finally:
            if own_transaction:
                self.connection.rollback()  # End this read snapshot, never a caller's write transaction.
