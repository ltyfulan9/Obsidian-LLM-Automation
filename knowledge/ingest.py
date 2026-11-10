"""Read only explicitly configured sources. Native logs are best-effort adapters."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from .common import KnowledgeError, clean_text, day_of, digest


@dataclass
class Document:
    id: str
    source: str
    origin: str
    kind: str
    day: str
    title: str
    text: str
    topics: list[str]

    def to_dict(self):
        return asdict(self)


def text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", "")) for block in content
            if isinstance(block, dict) and block.get("type") in {"text", "input_text", "output_text"}
        )
    return ""


def jsonl_records(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    records = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
        except ValueError as exc:
            # A running session may be in the middle of writing its last line.
            if index == len(lines) - 1 and not line.endswith("\n"):
                continue
            raise KnowledgeError(f"Malformed JSONL at line {index + 1}: {path.name}") from exc
    return records


def native_messages(records: list[dict], kind: str) -> list[tuple[str, str, object]]:
    messages = []
    for record in records:
        if kind == "codex":
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if record.get("type") == "response_item" and payload.get("type") == "message":
                role = payload.get("role")
                if role in {"user", "assistant"}:
                    text = text_content(payload.get("content"))
                    if text.strip():
                        messages.append((role, text, record.get("timestamp")))
        elif kind == "claude" and not record.get("isSidechain"):
            message = record.get("message", {})
            if record.get("type") in {"user", "assistant"} and isinstance(message, dict):
                role = message.get("role", record["type"])
                text = text_content(message.get("content"))
                if role in {"user", "assistant"} and text.strip():
                    messages.append((role, text, record.get("timestamp")))
    if kind == "codex" and not messages:
        # Legacy fallback only: never ingest response items and event duplicates together.
        for record in records:
            payload = record.get("payload", {})
            if record.get("type") != "event_msg" or not isinstance(payload, dict):
                continue
            role = {"user_message": "user", "agent_message": "assistant"}.get(payload.get("type"))
            if role and isinstance(payload.get("message"), str):
                messages.append((role, payload["message"], record.get("timestamp")))
    return messages


def export_conversations(value) -> list[tuple[str, list[tuple[str, str, object]]]]:
    conversations = value if isinstance(value, list) else [value]
    result = []
    for index, conversation in enumerate(conversations):
        if not isinstance(conversation, dict):
            raise KnowledgeError("Conversation export must contain JSON objects")
        records = conversation.get("messages", conversation.get("chat_messages", []))
        if not isinstance(records, list):
            raise KnowledgeError("Conversation messages must be a list")
        messages = []
        for record in records:
            if not isinstance(record, dict):
                continue
            role = record.get("role", record.get("sender"))
            role = {"human": "user", "bot": "assistant"}.get(role, role)
            text = text_content(record.get("content", record.get("text", "")))
            if role in {"user", "assistant"} and text.strip():
                messages.append((role, text, record.get("timestamp", record.get("created_at", conversation.get("created_at")))))
        identity = str(conversation.get("id", conversation.get("uuid", index)))
        result.append((identity, messages))
    return result


SKIP_DIRS = {".git", ".obsidian", ".knowledge", ".local-state", "node_modules", ".venv", "__pycache__"}


def is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def source_files(source: dict, workspace: Path):
    # macOS /var aliases and Windows short/junction paths must be compared canonically.
    workspace = workspace.expanduser().resolve()
    base = Path(source["path"]).expanduser().resolve()
    if not base.exists():
        raise KnowledgeError(f"Configured source is missing: {source['name']}")
    if base == workspace or workspace.is_relative_to(base):
        raise KnowledgeError("Source must not contain the output workspace")
    extensions = {"markdown": {".md"}, "codex": {".jsonl"}, "claude": {".jsonl"}, "export": {".md", ".json", ".jsonl"}}[source["kind"]]
    if base.is_file():
        candidates = [base]
    else:
        candidates = []
        for folder, directories, files in os.walk(base, followlinks=False):
            directories[:] = sorted(d for d in directories if d not in SKIP_DIRS and not is_link(Path(folder) / d))
            candidates.extend(Path(folder) / name for name in sorted(files))
    for path in candidates:
        if is_link(path) or path.suffix.lower() not in extensions:
            continue
        relative = path.name if base.is_file() else path.relative_to(base).as_posix()
        if "subagents" in Path(relative).parts:
            continue
        include = source.get("include", ["*"])
        exclude = source.get("exclude", [])
        if not any(fnmatch.fnmatch(relative, glob) for glob in include) or any(fnmatch.fnmatch(relative, glob) for glob in exclude):
            continue
        yield path, relative


def read_source(source: dict, config: dict, workspace: Path) -> list[Document]:
    documents = []
    privacy = config.get("privacy", {})
    for path, relative in source_files(source, workspace):
        if path.stat().st_size > config.get("max_file_bytes", 32 * 1024 * 1024):
            raise KnowledgeError(f"Source file exceeds max_file_bytes: {source['name']}/{relative}")
        kind = source["kind"]
        origin = clean_text(relative, privacy)
        fallback = path.stat().st_mtime
        tz = config.get("timezone", "local")

        def document(day, title, text, identity="", topics=None):
            if source.get("since") and day < source["since"]:
                return
            stable = digest(f"{source['name']}\0{relative}\0{identity}\0{day}")[:24]
            documents.append(Document(stable, source["name"], origin, kind, day,
                                      clean_text(title, privacy)[:160], clean_text(text, privacy), topics or []))

        if path.suffix.lower() == ".md":
            text = path.read_text(encoding="utf-8-sig")
            date = re.search(r"(?m)^date:\s*[\"']?(\d{4}-\d{2}-\d{2})", text) or re.search(r"\d{4}-\d{2}-\d{2}", path.stem)
            day = day_of(date.group(1) if date and date.lastindex else date.group(0) if date else None, fallback, tz)
            heading = re.search(r"(?m)^#\s+(.+)$", text)
            tags = re.search(r"(?m)^tags:\s*\[([^\]]*)\]", text)
            topics = [tag.strip(" '\"") for tag in tags.group(1).split(",") if tag.strip()] if tags else []
            document(day, heading.group(1) if heading else path.stem, text, topics=topics)
            continue
        if kind in {"codex", "claude"}:
            groups = [("", native_messages(jsonl_records(path), kind))]
        else:
            value = jsonl_records(path) if path.suffix.lower() == ".jsonl" else json.loads(path.read_text(encoding="utf-8-sig"))
            # A flat generic JSONL stream of role/content messages is one conversation.
            if isinstance(value, list) and value and isinstance(value[0], dict) and "role" in value[0]:
                value = {"messages": value}
            groups = export_conversations(value)
        for identity, messages in groups:
            by_day = {}
            for role, text, stamp in messages:
                # CLI environment metadata is not user-authored conversation material.
                text = re.sub(r"<(environment_context|permissions_instructions)>.*?</\1>", "", text, flags=re.S).strip()
                if text:
                    by_day.setdefault(day_of(stamp, fallback, tz), []).append(f"## {role}\n\n{text}")
            for day, parts in sorted(by_day.items()):
                first = next((part.split("\n\n", 1)[1].splitlines()[0] for part in parts if part.startswith("## user")), path.stem)
                document(day, first[:100], "\n\n".join(parts), identity)
    return documents
