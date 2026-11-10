"""A bounded conversation-summary package carried by Magpie's existing skill backup."""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .common import KnowledgeError, SECRET, get_timezone, read_json, write_json

PACKAGE = "personal-chat-digest"
MAX_PLAIN_BYTES = 256 * 1024


def export_bundle(rows: list[dict], output: Path, config: dict) -> dict:
    settings = config.get("magpie", {})
    days = int(settings.get("keep_days", 7))
    limit = int(settings.get("max_kib", 64)) * 1024
    if not 1 <= days <= 365 or not 4 * 1024 <= limit <= 1024 * 1024:
        raise KnowledgeError("Magpie bundle requires 1..365 days and 4..1024 KiB")
    today = datetime.now().astimezone(get_timezone(config.get("timezone", "local"))).date()
    since = (today - timedelta(days=days - 1)).isoformat()
    candidates = sorted((row for row in rows if row["document"]["kind"] in {"codex", "claude", "export"}
                         and since <= row["document"]["day"] <= today.isoformat()),
                        key=lambda row: (row["document"]["day"], row["document"]["id"]), reverse=True)
    records = []
    for row in candidates[:200]:
        document, summary = row["document"], row["summary"]
        records.append({"id": document["id"], "date": document["day"], "kind": document["kind"],
                        "title": summary["title"][:120], "topics": summary["topics"][:6], "method": summary.get("method", "unknown"),
                        "summary": summary["summary"][:600], "key_points": [v[:150] for v in summary["key_points"][:4]],
                        "decisions": [v[:180] for v in summary["decisions"][:3]],
                        "questions": [v[:180] for v in summary["questions"][:3]]})
    while True:
        content = json.dumps({"version": 1, "records": records}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if SECRET.search(content.decode()):
            raise KnowledgeError("Secret-like content detected in conversation summary bundle")
        compressed = gzip.compress(content, compresslevel=9, mtime=0)
        if len(compressed) <= limit and len(content) <= MAX_PLAIN_BYTES:
            break
        if not records:
            raise KnowledgeError("Bundle metadata exceeds the configured budget")
        records.pop()  # Oldest first; the complete knowledge remains in the local catalog.
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "conversations.json.gz"
    if not destination.exists() or destination.read_bytes() != compressed:
        fd, temporary = tempfile.mkstemp(prefix=".digest-", dir=output)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(compressed)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    manifest = {"version": 1, "from": since, "through": today.isoformat(), "included": len(records),
                "omitted_for_budget": len(candidates) - len(records), "gzip_bytes": len(compressed),
                "plain_bytes": len(content), "max_gzip_bytes": limit, "full_transcripts": False}
    write_json(output / "manifest.json", manifest)
    return manifest


def verify_target(config: dict) -> Path:
    settings = config.get("magpie", {})
    if not settings.get("executable") or not settings.get("data_dir"):
        raise KnowledgeError("Set magpie.executable and magpie.data_dir before using --magpie")
    if not shutil.which(settings["executable"]):
        raise KnowledgeError("Configured Magpie executable is not available")
    data = Path(settings["data_dir"]).expanduser().resolve()
    connection = read_json(data / "sync.json")
    address = connection.get("url", "")
    match = re.fullmatch(r"github://([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/.*)?", address)
    if not match or not connection.get("library", True):
        raise KnowledgeError("Magpie GitHub sync must be configured with Library included")
    from .publish import run
    if run(["gh", "api", f"repos/{match.group(1)}", "--jq", ".private"], data) != "true":
        raise KnowledgeError("Magpie destination must be a verified private GitHub repository")
    library = read_json(data / "library.json")
    entry = next((skill for skill in library.get("skills", []) if skill.get("name") == PACKAGE), None)
    if not entry:
        raise KnowledgeError("Import the personal-chat-digest integration package into Magpie Library once before using --magpie")
    output = data / "library" / "skills" / PACKAGE
    source = entry.get("source") or {}
    if source.get("kind") == "folder" and source.get("dir"):
        output = Path(source["dir"]).expanduser().resolve()
    if not (output / "SKILL.md").exists():
        raise KnowledgeError("The registered Magpie integration package is missing")
    return output


def sync_bundle(rows: list[dict], config: dict, output: Path) -> dict:
    manifest = export_bundle(rows, output, config)
    from .publish import run
    # Magpie owns credentials, encryption, remote merging and backup publication.
    run([config["magpie"]["executable"], "github", "now"], output, timeout=120)
    return manifest
