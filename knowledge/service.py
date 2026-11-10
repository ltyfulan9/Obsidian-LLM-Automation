"""Orchestrate ingestion, transactional summaries, projections and optional publication."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .catalog import Catalog
from .common import KnowledgeError, atomic_write, digest, read_json, workspace_lock, write_json
from .config import validate_config
from .ingest import read_source
from .publish import private_target, publish
from .render import build
from .summarize import fingerprint, summarize
from .magpie import export_bundle, sync_bundle, verify_target
from .runstate import tracked_run

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
    return validate_config(read_json(root / ".knowledge" / "config.json"))


def ensure_notes_guide(root: Path) -> None:
    notes = root / "Notes"
    if not notes.resolve().is_relative_to(root.resolve()):
        raise KnowledgeError("Notes must stay inside the knowledge workspace")
    notes.mkdir(exist_ok=True)
    try:
        with (notes / "README.md").open("x", encoding="utf-8", newline="\n") as output:
            output.write("# 手写知识与补充\n\n这是手写知识的默认入口，可以自由编辑；工具不会覆盖已有文件。\n\n"
                         "[知识库首页](../Home.md) · [日期时间线](../Timeline.md) · [承诺与结果](../Tasks.md) · [行为复盘](../Review.md)\n\n"
                         "直接修改生成页会触发保护；把自己的补充保存在本目录，保留原始来源供查证。\n")
    except FileExistsError:
        pass


def initialize(root: Path) -> None:
    root = root.expanduser().resolve()
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
    ensure_notes_guide(root)
    write_json(root / ".knowledge" / "config.json", DEFAULT_CONFIG)
    ignore = root / ".gitignore"
    previous = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    atomic_write(ignore, previous.rstrip() + "\n# Local knowledge state and authentication\n.knowledge/\n.obsidian/\n.env\n.env.*\n*.pem\n*.key\n")
    catalog = Catalog(root, create=True)
    try:
        build(root, catalog.rows(), DEFAULT_CONFIG, catalog.personal_state())
    finally:
        catalog.close()


def sync(root: Path, engine_name: str | None = None, push: bool = False, magpie: bool = False, *, run_id: str | None = None) -> dict:
    with workspace_lock(root), tracked_run(root, push=push, magpie=magpie, run_id=run_id) as attempt:
        config = load_config(root)
        if engine_name:
            config["engine"]["name"] = engine_name
            validate_config(config)
        if push:
            # Refuse public destinations before reading any configured source.
            attempt.phase("verify_target")
            private_target(root)
        magpie_output = None
        if magpie:
            attempt.phase("verify_magpie")
            magpie_output = verify_target(config)
        attempt.phase("catalog")
        catalog = Catalog(root)
        try:
            attempt.phase("collect")
            documents, seen = [], {}
            for source in config["sources"]:
                imported = read_source(source, config, root)
                documents.extend(imported)
                seen[source["name"]] = {document.id for document in imported}
            engine_hash = fingerprint(config["engine"])
            engine = dict(config["engine"], cache_dir=str(root / ".knowledge/summary-cache"))
            changed, unchanged = 0, 0
            attempt.phase("summarize")
            with catalog.connection:
                for document in documents:
                    data = document.to_dict()
                    content_hash = digest(json.dumps(data, sort_keys=True, ensure_ascii=False))
                    current = catalog.current(document.id)
                    if current and current["content_hash"] == content_hash and current["engine_hash"] == engine_hash:
                        unchanged += 1
                        continue
                    summary = summarize(document, engine, config.get("privacy", {}))
                    summary["method"] = config["engine"]["name"]
                    catalog.save(data, summary, content_hash, engine_hash)
                    changed += 1
                for source_name, present in seen.items():
                    catalog.mark_missing(source_name, present)
            attempt.confirm("catalog")
            attempt.phase("render")
            ensure_notes_guide(root)
            count = build(root, catalog.rows(), config, catalog.personal_state())
            attempt.confirm("rendered")
            result = {"tool_version": __version__, "time": datetime.now(timezone.utc).isoformat(),
                      "run_id": attempt.data["run_id"],
                      "requested": {"push": push, "magpie": magpie},
                      "documents": len(documents), "updated": changed, "unchanged": unchanged, "generated_files": count,
                      "engine": config["engine"]["name"], "published_commit": None}
            if push:
                attempt.phase("publish")
                result["published_commit"] = publish(root, config.get("include_raw", False))
                attempt.confirm("published")
            if magpie_output is not None:
                attempt.phase("magpie")
                result["magpie_bundle"] = sync_bundle(catalog.rows(), config, magpie_output)
                attempt.confirm("magpie")
            attempt.phase("record")
            write_json(root / ".knowledge" / "last-run.json", result)
            attempt.result = result
            return result
        finally:
            catalog.close()


def export_magpie(root: Path, output: Path) -> dict:
    config = load_config(root)
    with workspace_lock(root):
        catalog = Catalog(root)
        try:
            return export_bundle(catalog.rows(), output, config)
        finally:
            catalog.close()


def rebuild(root: Path) -> int:
    config = load_config(root)
    with workspace_lock(root):
        catalog = Catalog(root)
        try:
            ensure_notes_guide(root)
            return build(root, catalog.rows(), config, catalog.personal_state())
        finally:
            catalog.close()


def search(root: Path, query: str, *, since: str | None = None, until: str | None = None, kind: str | None = None) -> list[dict]:
    from .query import search_catalog
    load_config(root)
    catalog = Catalog(root)
    try:
        return search_catalog(catalog.rows(), catalog.personal_state(), query, since=since, until=until, kind=kind)
    finally:
        catalog.close()
