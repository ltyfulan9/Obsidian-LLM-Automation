"""Orchestrate ingestion, transactional summaries, projections and optional publication."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .catalog import Catalog
from .common import KnowledgeError, atomic_write, digest, get_timezone, read_json, workspace_lock, write_json
from .ingest import read_source
from .publish import private_target, publish
from .render import build
from .summarize import fingerprint, summarize

DEFAULT_CONFIG = {
    "version": 2,
    "timezone": "local",
    "sources": [],
    "engine": {"name": "extract", "model": None, "command": None, "timeout_seconds": 180, "chunk_chars": 16000},
    "privacy": {"redact_local_paths": True, "redact_emails": True},
    "include_raw": False,
    "graph_max_documents": 120,
    "max_file_bytes": 33554432,
}


def load_config(root: Path) -> dict:
    config = read_json(root / ".knowledge" / "config.json")
    if not isinstance(config, dict) or not isinstance(config.get("engine"), dict):
        raise KnowledgeError("Config must contain an engine object")
    if config.get("version") != 2 or config["engine"].get("name") not in {"extract", "codex", "claude"}:
        raise KnowledgeError("Unsupported config version or summary engine")
    if not isinstance(config.get("sources"), list) or not isinstance(config.get("privacy", {}), dict):
        raise KnowledgeError("Config sources must be a list and privacy an object")
    if not isinstance(config.get("timezone", "local"), str):
        raise KnowledgeError("Timezone must be a string")
    get_timezone(config.get("timezone", "local"))
    for key, fallback in (("timeout_seconds", 180), ("chunk_chars", 16000)):
        value = config["engine"].get(key, fallback)
        if type(value) is not int or value <= 0:
            raise KnowledgeError(f"Engine {key} must be a positive integer")
    for key in ("model", "command"):
        if config["engine"].get(key) is not None and not isinstance(config["engine"][key], str):
            raise KnowledgeError(f"Engine {key} must be a string or null")
    for key, fallback in (("graph_max_documents", 120), ("max_file_bytes", 33554432)):
        if type(config.get(key, fallback)) is not int or config.get(key, fallback) <= 0:
            raise KnowledgeError(f"{key} must be a positive integer")
    if type(config.get("include_raw", False)) is not bool:
        raise KnowledgeError("include_raw must be a boolean")
    names = set()
    for source in config.get("sources", []):
        if not isinstance(source, dict):
            raise KnowledgeError("Each source must be an object")
        if source.get("kind") not in {"markdown", "codex", "claude", "export"} or not source.get("path"):
            raise KnowledgeError("Invalid source configuration")
        name = source.get("name", "")
        if not re.fullmatch(r"[\w\-]{1,60}", name) or name in names:
            raise KnowledgeError("Source names must be unique letters, numbers, underscores or hyphens")
        names.add(name)
        for key in ("include", "exclude"):
            if key in source and (not isinstance(source[key], list) or any(not isinstance(v, str) for v in source[key])):
                raise KnowledgeError("Source glob rules must be lists of strings")
    return config


def initialize(root: Path) -> None:
    code_root = Path(__file__).resolve().parent.parent
    if root == code_root or root.is_relative_to(code_root):
        raise KnowledgeError("Create the private knowledge workspace outside the public tool checkout")
    for ancestor in (root, *root.parents):
        project = ancestor / "pyproject.toml"
        if project.exists() and 'name = "obsidian-llm-knowledge"' in project.read_text(encoding="utf-8"):
            raise KnowledgeError("Create the private knowledge workspace outside the public tool checkout")
    if (root / ".knowledge" / "config.json").exists():
        raise KnowledgeError("Workspace already initialized")
    # Avoid overwriting an existing vault's entrance or handwritten files.
    if any((root / filename).exists() for filename in ("Home.md", "Timeline.md", ".knowledge")):
        raise KnowledgeError("Choose a fresh workspace; existing notes are not overwritten")
    root.mkdir(parents=True, exist_ok=True)
    (root / ".knowledge").mkdir()
    (root / "Notes").mkdir(exist_ok=True)
    write_json(root / ".knowledge" / "config.json", DEFAULT_CONFIG)
    ignore = root / ".gitignore"
    previous = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    atomic_write(ignore, previous.rstrip() + "\n# Local knowledge state and authentication\n.knowledge/\n.obsidian/\n.env\n.env.*\n*.pem\n*.key\n")
    catalog = Catalog(root)
    try:
        build(root, catalog.rows(), DEFAULT_CONFIG)
    finally:
        catalog.close()


def sync(root: Path, engine_name: str | None = None, push: bool = False) -> dict:
    config = load_config(root)
    if engine_name:
        config["engine"]["name"] = engine_name
    with workspace_lock(root):
        if push:
            # Refuse public destinations before reading any configured source.
            private_target(root)
        documents, seen = [], {}
        for source in config["sources"]:
            imported = read_source(source, config, root)
            documents.extend(imported)
            seen[source["name"]] = {document.id for document in imported}
        engine_hash = fingerprint(config["engine"])
        changed, unchanged = 0, 0
        catalog = Catalog(root)
        try:
            with catalog.connection:
                for document in documents:
                    data = document.to_dict()
                    content_hash = digest(json.dumps(data, sort_keys=True, ensure_ascii=False))
                    current = catalog.current(document.id)
                    if current and current["content_hash"] == content_hash and current["engine_hash"] == engine_hash:
                        unchanged += 1
                        continue
                    summary = summarize(document, config["engine"], config.get("privacy", {}))
                    summary["method"] = config["engine"]["name"]
                    catalog.save(data, summary, content_hash, engine_hash)
                    changed += 1
                for source_name, present in seen.items():
                    catalog.mark_missing(source_name, present)
            count = build(root, catalog.rows(), config)
            result = {"tool_version": __version__, "time": datetime.now(timezone.utc).isoformat(),
                      "documents": len(documents), "updated": changed, "unchanged": unchanged, "generated_files": count,
                      "engine": config["engine"]["name"], "published_commit": None}
            if push:
                result["published_commit"] = publish(root, config.get("include_raw", False))
            write_json(root / ".knowledge" / "last-run.json", result)
            return result
        finally:
            catalog.close()


def rebuild(root: Path) -> int:
    config = load_config(root)
    with workspace_lock(root):
        catalog = Catalog(root)
        try:
            return build(root, catalog.rows(), config)
        finally:
            catalog.close()


def search(root: Path, query: str) -> list[dict]:
    load_config(root)
    catalog = Catalog(root)
    try:
        terms = query.casefold().split()
        return [{"date": row["document"]["day"], "title": row["summary"]["title"],
                 "topics": row["summary"]["topics"], "file": f"Sources/{row['document']['id']}.md"}
                for row in catalog.rows()
                if all(term in json.dumps(row, ensure_ascii=False).casefold() for term in terms)][:50]
    finally:
        catalog.close()
