"""Read-only diagnostics; source content, model calls and network are opt-in elsewhere."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .catalog import validate_schema
from .common import KnowledgeError, digest, read_json
from .config import validate_config
from .projection_store import generated_area, registry, target_path
from .publish import private_target
from .runstate import status as operation_status

def doctor(root: Path, check_publish: bool = False) -> dict:
    """Check local metadata by default; never repair, initialize or run a provider."""
    checks = []

    def record(identifier: str, status: str, message: str, next_step: str = "") -> None:
        checks.append({"id": identifier, "status": status, "message": message, "next_step": next_step})

    def result() -> dict:
        return {"ok": not any(check["status"] == "error" for check in checks), "checks": checks}

    try:
        root = root.expanduser().resolve()
        if not root.is_dir():
            record("workspace", "error", "Workspace directory does not exist.", "Run knowledge init with a fresh workspace path.")
            return result()
        record("workspace", "ok", "Workspace directory exists; no files were changed.")
        config = validate_config(read_json(root / ".knowledge/config.json"))
    except (KnowledgeError, OSError, ValueError, RuntimeError) as exc:
        record("config", "error", str(exc) if isinstance(exc, KnowledgeError) else "Cannot inspect workspace configuration.",
               "Check .knowledge/config.json, or initialize a fresh workspace; keep the existing folder intact.")
        return result()
    record("config", "ok", "Configuration values are valid.")

    state_unreadable = False
    try:
        operation = operation_status(root)
    except (KnowledgeError, OSError, ValueError, RuntimeError):
        operation = {}
        state_unreadable = True
        record("operation", "error", "Latest-attempt metadata cannot be inspected; an earlier success is not proof of this run.",
               "Keep existing files and inspect local run metadata and scheduler logs before retrying.")
    attempt = operation.get("last_attempt") or {}
    busy = operation.get("workspace_busy")
    deferred = state_unreadable or busy is True or attempt.get("status") == "running"
    if busy is True or attempt.get("status") == "running":
        message = "A knowledge operation is active; live catalog and page checks were deferred." if busy is True else \
                  "A run is recorded as running, but active workspace ownership was not confirmed; live checks were deferred."
        record("operation", "warning", message,
               "Wait for the operation or check its system task, then run knowledge status --format text and doctor again; do not delete run.lock.")
    elif attempt.get("status") in {"failed", "interrupted"}:
        phase = {"configuration": "configuration validation", "verify_target": "private-target verification",
                 "verify_magpie": "Magpie verification", "collect": "source collection", "summarize": "summarizing",
                 "catalog": "catalog saving", "render": "page generation", "publish": "publication",
                 "magpie": "Magpie synchronization", "record": "run-result recording"}.get(attempt.get("phase"), "a recorded phase")
        confirmed = [label for key, label in (("catalog", "catalog"), ("rendered", "pages"), ("published", "publication"), ("magpie", "Magpie sync"))
                     if attempt.get("saved", {}).get(key) is True]
        message = f"Latest recorded sync attempt {attempt['status']} during {phase}. Confirmed stages: {', '.join(confirmed) or 'none'}; remaining stages are not confirmed."
        if operation.get("last_run"):
            message += " The retained earlier success does not describe this attempt."
        record("operation", "error", message, attempt.get("next_step") or
               "Inspect knowledge status --format text and preserve current files before retrying the unfinished stage.")
    elif attempt.get("status") == "succeeded":
        record("operation", "ok", "Latest recorded sync attempt succeeded; system scheduler installation was not queried.")
    elif not state_unreadable:
        message = "An earlier success exists, but no latest-attempt record is available from this version." if operation.get("last_run") else \
                  "No sync attempt has been recorded by this version yet."
        record("operation", "warning", message, "Run knowledge sync when ready; scheduler installation is a separate step.")

    roots = []
    for source in config["sources"]:
        identifier = "source:" + source["name"]
        try:
            path = Path(source["path"]).expanduser().resolve()
            if not path.exists():
                record(identifier, "error", "Configured source does not exist.", "Correct this source's path in .knowledge/config.json or reconnect its drive.")
                continue
            if path == root or root.is_relative_to(path):
                record(identifier, "error", "Source contains the output workspace.", "Choose a separate source directory that cannot collect generated output.")
                continue
            if path.is_relative_to(root):
                if generated_area(path.relative_to(root)):
                    record(identifier, "error", "Source points to generated output.", "Use original notes or Notes/ instead of a generated directory.")
                    continue
            roots.append((source["name"], path))
            record(identifier, "ok", "Source path exists; its contents were not opened.")
        except (OSError, ValueError, RuntimeError):
            record(identifier, "error", "Source path cannot be inspected.", "Correct this source's path in .knowledge/config.json and check filesystem access.")
    if not config["sources"]:
        record("sources", "warning", "No external sources configured; manual records can still be used.",
               "Add an explicit source with knowledge source before collecting notes or conversations.")
    for index, (name, path) in enumerate(roots):
        for other_name, other_path in roots[index + 1:]:
            if path == other_path or path.is_relative_to(other_path) or other_path.is_relative_to(path):
                record("overlap:" + name + ":" + other_name, "warning", "Configured sources overlap and may import duplicate material.",
                       "Review these sources' include/exclude filters or keep one source for this directory.")

    engine = config["engine"]
    if engine["name"] == "extract":
        record("engine", "ok", "Local extraction needs no model executable or network.")
    elif shutil.which(engine.get("command") or engine["name"]):
        record("engine", "ok", "Model executable found; authentication and inference were not tested.")
    else:
        record("engine", "error", "Configured model executable was not found.",
               "Install the selected CLI or set engine.command to its executable; authenticate it separately.")

    database = root / ".knowledge/catalog.sqlite3"
    if deferred:
        record("catalog", "warning", "Live catalog integrity inspection was deferred; no catalog was created or repaired.",
               "After the active operation or metadata issue is resolved, run doctor again.")
    elif not database.is_file():
        record("catalog", "error", "Local catalog is missing.", "Restore a state backup; do not replace an existing knowledge folder with an empty catalog.")
    elif any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-journal")):
        record("catalog", "warning", "A database journal exists; integrity inspection was deferred.", "Let the active sync finish, then run doctor again.")
    else:
        try:
            # immutable prevents SQLite creating journals or locking sidecars during diagnostics.
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
                intact = connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                validate_schema(connection)
            if not intact or "documents" not in tables:
                raise sqlite3.DatabaseError("Invalid catalog")
            if not {"checkins", "commitments", "commitment_events"}.issubset(tables):
                record("catalog", "warning", "Catalog is readable but needs the current personal-record tables.", "Run knowledge build to apply the compatible catalog upgrade.")
            else:
                record("catalog", "ok", "Catalog passed a read-only SQLite quick check.")
        except (KnowledgeError, sqlite3.Error, OSError, ValueError):
            record("catalog", "error", "Catalog cannot pass its read-only integrity check.", "Keep the current files and restore a verified state backup into a separate directory.")

    if deferred:
        record("generated", "warning", "Live generated-page checks were deferred; in-progress changes are not classified as manual edits.",
               "After the active operation or metadata issue is resolved, run doctor again.")
    elif (root / ".knowledge/render-journal.json").exists():
        record("generated", "warning", "An interrupted generation is pending; pages were not modified.", "Run knowledge build to validate and resume the pending generation.")
    elif not (root / ".knowledge/generated.json").is_file():
        record("generated", "error", "Generated-file ownership registry is missing.", "Restore generated.json from a state backup before rebuilding existing generated pages.")
    else:
        try:
            previous = registry(root)
            missing, edited = [], []
            for relative, expected in previous.items():
                path = target_path(root, relative)
                if not path.exists():
                    missing.append(relative)
                elif digest(path.read_text(encoding="utf-8")) != expected:
                    edited.append(relative)
            if edited:
                record("generated", "error", "Manual edits detected in: " + ", ".join(sorted(edited)[:3]),
                       "Move intended edits to Notes/, restore the generated page, then run knowledge build.")
            elif missing:
                record("generated", "warning", f"{len(missing)} generated pages are missing.", "Run knowledge build to recreate missing pages without model calls.")
            else:
                record("generated", "ok", "Generated pages match their ownership registry.")
        except (KnowledgeError, OSError, ValueError):
            record("generated", "error", "Generated-file registry or pages cannot be validated.", "Keep current files and restore the registry/pages from a verified state backup.")

    if check_publish:
        try:
            private_target(root)
            record("publish", "ok", "GitHub target was verified private; nothing was uploaded.")
        except (KnowledgeError, OSError, ValueError):
            record("publish", "error", "Private GitHub publication is not ready.",
                   "Check main, the GitHub origin, gh authentication and private repository visibility.")
    return result()
