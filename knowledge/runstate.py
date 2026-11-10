"""Durable sync attempts and nonmutating status, separate from last success."""

from __future__ import annotations

import errno
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .common import KnowledgeError, read_json, write_json
from .config import validate_config

HINTS = {
    "configuration": "Check .knowledge/config.json with knowledge doctor before retrying sync.",
    "verify_target": "Run knowledge doctor --publish and verify the private GitHub target before retrying.",
    "verify_magpie": "Check the registered Magpie integration before retrying sync --magpie.",
    "catalog": "Keep existing files; restore a verified state backup into a new workspace.",
    "collect": "Run knowledge doctor, correct missing or invalid sources, then retry sync.",
    "summarize": "Check the configured CLI authentication/model, then retry sync; successful chunks are cached.",
    "render": "Preserve handwritten edits in Notes/, run knowledge build, then retry sync to verify the full pipeline.",
    "publish": "Local knowledge may already be saved. Verify Git state, retry knowledge publish, then sync --push to verify the full pipeline.",
    "magpie": "Local knowledge may already be saved. Check Magpie, then retry sync --magpie.",
    "record": "Check local storage access; inspect saved results with knowledge doctor before retrying.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state(root: Path) -> dict:
    path = root / ".knowledge/run-state.json"
    if path.exists():
        value = read_json(path)
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
            raise KnowledgeError("Run metadata is invalid; preserve it and inspect a verified backup")
        attempt, success = value.get("last_attempt"), value.get("last_success")
        if attempt is not None:
            valid = isinstance(attempt, dict) and isinstance(attempt.get("status"), str) and attempt["status"] in {"running", "failed", "succeeded"}
            valid = valid and isinstance(attempt.get("phase"), str) and attempt["phase"] in {*HINTS, "complete"}
            saved = attempt.get("saved") if isinstance(attempt, dict) else None
            valid = valid and isinstance(saved, dict) and all(key in {"catalog", "rendered", "published", "magpie"}
                                                              and type(flag) is bool for key, flag in saved.items())
            if not valid:
                raise KnowledgeError("Run attempt metadata is invalid; keep the current file for recovery")
        if success is not None and not isinstance(success, dict):
            raise KnowledgeError("Last-success metadata is invalid")
        return value
    legacy = root / ".knowledge/last-run.json"
    success = read_json(legacy) if legacy.exists() else None
    if success is not None and not isinstance(success, dict):
        raise KnowledgeError("Last-success metadata is invalid")
    return {"version": 1, "last_attempt": None, "last_success": success}


def workspace_busy(root: Path) -> bool | None:
    """Probe the advisory lock without creating, deleting or writing any file."""
    path = root / ".knowledge/run.lock"
    if not path.exists():
        return False
    try:
        if path.stat().st_size == 0:
            return None
        handle = path.open("r+b")
    except OSError:
        return None
    with handle:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            return True if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} else None
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False


def status(root: Path) -> dict:
    """Read configuration and run metadata only; never open/create a catalog."""
    root = root.expanduser().resolve()
    if not (root / ".knowledge").is_dir():
        raise KnowledgeError("Workspace is not initialized; use knowledge init with a fresh path")
    try:
        config = validate_config(read_json(root / ".knowledge/config.json"))
        problem = None
    except KnowledgeError as exc:
        config = {"sources": [], "engine": {"name": None}}
        problem = str(exc)
    value = _state(root)
    busy = workspace_busy(root)
    attempt = dict(value["last_attempt"]) if value["last_attempt"] else None
    if attempt:
        attempt["next_step"] = HINTS.get(attempt["phase"], "Run knowledge doctor before retrying sync.") if attempt["status"] == "failed" else ""
        if attempt["status"] == "failed":
            attempt["error"] = "interrupted" if attempt.get("error") == "interrupted" else attempt["phase"] + "_failed"
    if attempt and attempt["status"] == "running" and busy is False:
        attempt["recorded_status"] = "running"
        attempt["status"] = "interrupted"
        attempt["error"] = "interrupted"
        attempt["next_step"] = HINTS.get(attempt.get("phase"), "Run knowledge doctor before retrying sync.")
    return {"sources": [{"name": source["name"], "kind": source["kind"]} for source in config["sources"]],
            "engine": config["engine"]["name"], "configuration_error": problem,
            "last_run": value["last_success"], "last_attempt": attempt, "workspace_busy": busy}


class RunAttempt:
    def __init__(self, root: Path, push: bool, magpie: bool, run_id: str | None = None):
        if run_id is not None and (not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id)):
            raise KnowledgeError("Run correlation ID must be a UUID hex value")
        self.root = root
        self.started = time.monotonic()
        self.envelope = _state(root)
        self.data = {"run_id": run_id or uuid.uuid4().hex, "status": "running", "phase": "configuration", "pid": os.getpid(),
                     "started_at": _now(), "finished_at": None, "elapsed_seconds": None,
                     "requested": {"push": push, "magpie": magpie},
                     "saved": {key: False for key in ("catalog", "rendered", "published", "magpie")},
                     "error": None, "next_step": ""}
        self.result = None
        self.save()

    def save(self) -> None:
        self.envelope["last_attempt"] = self.data
        write_json(self.root / ".knowledge/run-state.json", self.envelope)

    def phase(self, value: str) -> None:
        self.data["phase"] = value
        self.save()

    def confirm(self, value: str) -> None:
        self.data["saved"][value] = True
        self.save()

    def finish(self, failed: bool = False, interrupted: bool = False) -> None:
        self.data.update(status="failed" if failed else "succeeded", finished_at=_now(),
                         elapsed_seconds=round(time.monotonic() - self.started, 3))
        if failed:
            self.data["error"] = "interrupted" if interrupted else self.data["phase"] + "_failed"
            self.data["next_step"] = HINTS.get(self.data["phase"], "Run knowledge doctor before retrying sync.")
        else:
            self.data["phase"] = "complete"
            self.envelope["last_success"] = self.result
        self.save()


@contextmanager
def tracked_run(root: Path, *, push: bool = False, magpie: bool = False, run_id: str | None = None):
    """Caller holds the workspace lock; each attempt preserves the last success."""
    attempt = RunAttempt(root, push, magpie, run_id)
    try:
        yield attempt
    except BaseException as exc:
        try:
            attempt.finish(failed=True, interrupted=isinstance(exc, (KeyboardInterrupt, SystemExit)))
        except OSError:
            pass  # Preserve the original failure if local storage cannot record it.
        raise
    else:
        attempt.finish()


def append_log(root: Path, result: dict | None = None, *, run_id: str | None = None) -> None:
    """Append bounded operational metadata only, never an exception or provider body."""
    if not (root / ".knowledge").is_dir():
        return
    if result is not None:
        event = {"time": _now(), "run_id": result.get("run_id"), "status": "succeeded", "phase": "complete",
                 "requested": result.get("requested", {}),
                 "saved": {"catalog": True, "rendered": True, "published": bool(result.get("published_commit")),
                           "magpie": "magpie_bundle" in result},
                 **{key: result.get(key) for key in ("documents", "updated", "unchanged", "generated_files")}}
    else:
        try:
            latest = status(root)["last_attempt"] or {}
        except (KnowledgeError, OSError, ValueError):
            latest = {}
        if (run_id is not None and latest.get("run_id") != run_id) or latest.get("status") not in {"failed", "interrupted"}:
            event = {"time": _now(), "run_id": run_id, "status": "blocked", "phase": "start", "error": "start_failed"}
        else:
            event = {"time": _now(), **{key: latest.get(key) for key in ("run_id", "status", "phase", "saved", "error")}}
    with (root / ".knowledge/scheduler.jsonl").open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(event, ensure_ascii=False) + "\n")
