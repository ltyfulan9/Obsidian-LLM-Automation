"""Transactional catalog; generated Markdown is a rebuildable projection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class Catalog:
    def __init__(self, root: Path):
        self.connection = sqlite3.connect(root / ".knowledge" / "catalog.sqlite3")
        self.connection.row_factory = sqlite3.Row
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
