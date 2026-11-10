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
