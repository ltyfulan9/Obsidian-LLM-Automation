"""Shared value types and filesystem boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class KnowledgeError(Exception):
    """An actionable error suitable for CLI output, without transcript content."""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slug(text: str) -> str:
    label = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", text, flags=re.UNICODE).strip("-_ ")[:48]
    return (label or "topic") + "-" + digest(text)[:8]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".knowledge-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, data: object) -> None:
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise KnowledgeError(f"Cannot read JSON: {path.name}") from exc


def get_timezone(name: str):
    if name == "local":
        return None
    if name == "UTC":
        return timezone.utc
    if re.fullmatch(r"[+-]\d{2}:\d{2}", name):
        hours, minutes = map(int, name[1:].split(":"))
        if hours > 23 or minutes > 59:
            raise KnowledgeError("Invalid timezone offset")
        return timezone(timedelta(minutes=(hours * 60 + minutes) * (1 if name[0] == "+" else -1)))
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise KnowledgeError("Timezone unavailable; install tzdata or use an offset such as +08:00") from exc


def day_of(value: str | float | None, fallback: float, tz_name: str) -> str:
    try:
        if isinstance(value, (int, float)):
            stamp = datetime.fromtimestamp(value, timezone.utc)
        elif value:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=get_timezone(tz_name)) if tz_name != "local" else stamp.astimezone()
        else:
            stamp = datetime.fromtimestamp(fallback, timezone.utc)
        return stamp.astimezone(get_timezone(tz_name)).date().isoformat()
    except (ValueError, TypeError, OverflowError) as exc:
        raise KnowledgeError("Invalid source timestamp") from exc


SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,}|Bearer[ \t]+[A-Za-z0-9._~-]{20,}", re.I
)


def clean_text(text: str, privacy: dict) -> str:
    if SECRET.search(text):
        raise KnowledgeError("Secret-like content detected; review the source before importing")
    if privacy.get("redact_local_paths", True):
        text = re.sub(r"(?i)[A-Z]:[\\/]Users[\\/][^\s\\/\"<>]+", "~", text)
        text = re.sub(r"/(?:Users|home)/[^\s/\"<>]+", "~", text)
    if privacy.get("redact_emails", True):
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email redacted]", text)
    return text.replace("\x00", "")


@contextmanager
def workspace_lock(root: Path):
    lock = root / ".knowledge" / "run.lock"
    handle = lock.open("a+b")
    try:
        if lock.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise KnowledgeError("Another knowledge run holds this workspace lock") from exc
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        # Leave the inode in place. OS locks are released on process death;
        # deleting/recreating a lock file would allow an inode race on Unix.
