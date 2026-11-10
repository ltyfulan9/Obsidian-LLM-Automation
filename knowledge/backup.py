"""Private, verified workspace-state packages; never an external-source backup."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import unicodedata
import zipfile
import zlib
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import __version__
from .catalog import validate_schema
from .common import KnowledgeError, read_json, workspace_lock
from .config import validate_config
from .ingest import is_link
from .projection_store import MANAGED_DIRS, ROOT_FILES, registry, target_path

FORMAT = "obsidian-llm-knowledge-state"
VERSION = 1
MAX_FILES = 20000
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
REQUIRED = {".knowledge/catalog.sqlite3", ".knowledge/config.json", ".knowledge/generated.json", ".gitignore"}
OPTIONAL = {".knowledge/run-state.json", ".knowledge/last-run.json", ".knowledge/render-journal.json"}
RESERVED = {"CON", "PRN", "AUX", "NUL", *("COM" + str(i) for i in range(1, 10)), *("LPT" + str(i) for i in range(1, 10))}
AUTH_DIRS = {".git", ".codex", ".claude", ".ssh", ".obsidian", ".knowledge"}
AUTH_FILES = re.compile(r"^\.env(?:\..*)?$|^id_(?:rsa|ed25519)(?:\..*)?$|"
                        r"^(?:auth|credentials?|cookies?|tokens?)\.(?:json|ya?ml|txt|ini|toml|conf)$|\.(?:pem|p12|pfx|key)$", re.I)


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or any(ord(char) < 32 for char in name):
        raise KnowledgeError("State package contains an unsafe path")
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or path.as_posix() != name or any(part in {".", ".."} for part in path.parts):
        raise KnowledgeError("State package contains an unsafe path")
    if any(part.rstrip(" .") != part or part.split(".")[0].upper() in RESERVED for part in path.parts):
        raise KnowledgeError("State package contains a nonportable filename")
    if name in REQUIRED | OPTIONAL:
        return name
    if path.parts[0] == "Notes" and len(path.parts) > 1:
        if any(part.casefold() in AUTH_DIRS for part in path.parts[1:]) or AUTH_FILES.search(path.name):
            raise KnowledgeError("Notes contains authentication/settings material; keep it outside the state package")
        return name
    if name in ROOT_FILES or (len(path.parts) == 2 and path.parts[0] in MANAGED_DIRS and name.endswith((".md", ".canvas"))):
        return name
    raise KnowledgeError("State package contains a file outside the workspace-state boundary")


def _outside_public_checkout(path: Path) -> None:
    code_root = Path(__file__).resolve().parent.parent
    if path == code_root or path.is_relative_to(code_root):
        raise KnowledgeError("Private state packages and restored workspaces must stay outside the public tool checkout")
    for parent in path.parents:
        project = parent / "pyproject.toml"
        if project.is_file() and 'name = "obsidian-llm-knowledge"' in project.read_text(encoding="utf-8"):
            raise KnowledgeError("Private state packages and restored workspaces must stay outside the public tool checkout")


def _source(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(_safe_name(relative)).parts)
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        if (candidate.exists() and is_link(candidate)) or candidate.is_symlink():
            raise KnowledgeError("State backup cannot follow links")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise KnowledgeError("A workspace-state file is missing or outside the workspace")
    return path


def _unique_names(names: list[str]) -> None:
    canonical = {}
    for name in names:
        key = unicodedata.normalize("NFC", name).casefold()
        if key in canonical:
            raise KnowledgeError("State package contains duplicate or case/Unicode-conflicting paths")
        canonical[key] = name
    for key in canonical:
        if any(parent.as_posix() in canonical for parent in PurePosixPath(key).parents if parent.as_posix() != "."):
            raise KnowledgeError("State package contains a file/directory path conflict")


def _check_snapshot(root: Path) -> None:
    validate_config(read_json(root / ".knowledge/config.json"))
    owned = registry(root)
    if any(not re.fullmatch(r"[0-9a-f]{64}", checksum) for checksum in owned.values()):
        raise KnowledgeError("State package contains an invalid generated-file registry")
    try:
        with closing(sqlite3.connect((root / ".knowledge/catalog.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
            if database.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise sqlite3.DatabaseError("Invalid snapshot")
            validate_schema(database)
    except sqlite3.Error as exc:
        raise KnowledgeError("State package contains an invalid catalog") from exc


def backup(root: Path, output: Path) -> dict:
    """Snapshot only owned state and Notes, with SQLite's consistent online backup API."""
    try:
        root = root.expanduser().resolve()
        requested = output.expanduser()
        if requested.exists() or requested.is_symlink():
            raise KnowledgeError("Choose a new state-package filename; existing files are not overwritten")
        output = requested.resolve()
        if output.is_relative_to(root):
            raise KnowledgeError("Private state packages must be saved outside the knowledge workspace")
        _outside_public_checkout(output)
        _source(root, ".knowledge/config.json")
        with workspace_lock(root):
            generated = registry(root)
            names = set(REQUIRED)
            names.update(name for name in OPTIONAL if (root / name).exists())
            names.update(name for name in generated if (root / name).exists())
            journal_path = root / ".knowledge/render-journal.json"
            if journal_path.exists():
                journal = read_json(journal_path)
                if not isinstance(journal, dict) or not all(isinstance(journal.get(key), dict) for key in ("writes", "deletes", "manifest")):
                    raise KnowledgeError("Interrupted generation has an invalid recovery journal; keep existing files")
                # New pages may not be in the old ownership registry yet; keep edits to them too.
                for relative in set(journal["writes"]) | set(journal["deletes"]):
                    if target_path(root, relative).exists():
                        names.add(relative)
            notes = root / "Notes"
            if notes.exists():
                if is_link(notes):
                    raise KnowledgeError("State backup cannot follow links")
                for folder, directories, files in os.walk(notes, followlinks=False):
                    if any(is_link(Path(folder) / name) for name in directories):
                        raise KnowledgeError("State backup cannot follow links")
                    names.update((Path(folder) / name).relative_to(root).as_posix() for name in files)
            if len(names) > MAX_FILES:
                raise KnowledgeError("Workspace exceeds the state-package file limit")
            _unique_names(sorted(names))
            sources = {name: _source(root, name) for name in sorted(names)}
            if any(path.stat().st_size > MAX_FILE_BYTES for path in sources.values()) or sum(path.stat().st_size for path in sources.values()) > MAX_TOTAL_BYTES:
                raise KnowledgeError("Workspace exceeds the state-package size limit")
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".knowledge-backup-", dir=output.parent) as directory:
                snapshot = Path(directory) / "snapshot"
                snapshot.mkdir()
                database_path = snapshot / ".knowledge/catalog.sqlite3"
                database_path.parent.mkdir()
                with closing(sqlite3.connect(sources[".knowledge/catalog.sqlite3"].as_uri() + "?mode=ro", uri=True)) as source, \
                        closing(sqlite3.connect(database_path)) as copy:
                    source.backup(copy)
                manifest_files = {}
                total = 0
                for name, source in sources.items():
                    target = snapshot.joinpath(*PurePosixPath(name).parts)
                    before = source.stat()
                    if not 0 <= before.st_mtime_ns <= 2**63 - 1:
                        raise KnowledgeError("Workspace contains a timestamp outside the portable state-package range")
                    if name != ".knowledge/catalog.sqlite3":
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
                        after = source.stat()
                        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            raise KnowledgeError("Workspace changed while copying; pause edits and retry the backup")
                    size = target.stat().st_size
                    total += size
                    if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                        raise KnowledgeError("Workspace exceeds the state-package size limit")
                    checksum = hashlib.sha256()
                    with target.open("rb") as data:
                        for chunk in iter(lambda: data.read(1024 * 1024), b""):
                            checksum.update(chunk)
                    manifest_files[name] = {"sha256": checksum.hexdigest(), "bytes": size, "mtime_ns": before.st_mtime_ns}
                _check_snapshot(snapshot)
                manifest = {"format": FORMAT, "version": VERSION, "private": True, "tool_version": __version__,
                            "created_at": datetime.now(timezone.utc).isoformat(), "files": manifest_files}
                manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
                if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                    raise KnowledgeError("Workspace exceeds the state-package manifest limit")
                package = Path(directory) / "state.zip"
                descriptor = os.open(package, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
                        bundle.writestr("manifest.json", manifest_bytes)
                        for name in sorted(sources):
                            bundle.write(snapshot.joinpath(*PurePosixPath(name).parts), name)
                    stream.flush()
                    os.fsync(stream.fileno())
                # An exclusive hard link publishes the completed file without replacing a concurrent file.
                os.link(package, output)
                return {"backup": str(output), "files": len(manifest_files), "bytes": output.stat().st_size,
                        "uncompressed_bytes": total, "private_state": True, "source_attachments": False,
                        "pending_recovery": journal_path.exists()}
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        raise KnowledgeError("Cannot create private state package; existing workspace files were kept") from exc


def _json_unique(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise KnowledgeError("State-package manifest contains duplicate keys")
        result[key] = value
    return result


def _validated_contents(package: Path, destination: Path) -> dict:
    """Extract into an isolated temporary directory only after checking every entry name."""
    with zipfile.ZipFile(package) as bundle:
        infos = bundle.infolist()
        if len(infos) > MAX_FILES + 1:
            raise KnowledgeError("State package exceeds the file limit")
        names = []
        for info in infos:
            name = info.filename
            if info.orig_filename != name or info.is_dir():
                raise KnowledgeError("State package contains an unsafe path or directory entry")
            if name != "manifest.json":
                _safe_name(name)
            mode = info.external_attr >> 16
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG} or info.external_attr & 0x400:
                raise KnowledgeError("State package contains a link or unsupported file type")
            if info.flag_bits & 1 or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise KnowledgeError("State package uses unsupported encryption or compression")
            if info.file_size > (MAX_MANIFEST_BYTES if name == "manifest.json" else MAX_FILE_BYTES):
                raise KnowledgeError("State package exceeds the file-size limit")
            names.append(name)
        _unique_names(names)
        if "manifest.json" not in names:
            raise KnowledgeError("State-package manifest is missing")
        if sum(info.file_size for info in infos if info.filename != "manifest.json") > MAX_TOTAL_BYTES:
            raise KnowledgeError("State package exceeds the total expanded-size limit")
        manifest = json.loads(bundle.read("manifest.json"), object_pairs_hook=_json_unique)
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or type(manifest.get("version")) is not int \
                or manifest["version"] != VERSION or manifest.get("private") is not True or not isinstance(manifest.get("files"), dict):
            raise KnowledgeError("Unsupported state-package format or version")
        files = manifest["files"]
        if set(files) != set(names) - {"manifest.json"} or not REQUIRED.issubset(files):
            raise KnowledgeError("State-package file list is incomplete or does not match its manifest")
        total = 0
        for name, metadata in files.items():
            _safe_name(name)
            info = bundle.getinfo(name)
            if not isinstance(metadata, dict) or type(metadata.get("bytes")) is not int or metadata["bytes"] != info.file_size \
                    or not isinstance(metadata.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"]) \
                    or type(metadata.get("mtime_ns")) is not int or not 0 <= metadata["mtime_ns"] <= 2**63 - 1:
                raise KnowledgeError("State-package file metadata is invalid")
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            checksum, size = hashlib.sha256(), 0
            with bundle.open(info) as source, target.open("xb") as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                        raise KnowledgeError("State package exceeds the expanded-size limit")
                    checksum.update(chunk)
                    output.write(chunk)
            if size != metadata["bytes"] or checksum.hexdigest() != metadata["sha256"]:
                raise KnowledgeError("State-package checksum does not match")
            os.utime(target, ns=(metadata["mtime_ns"], metadata["mtime_ns"]))
    _check_snapshot(destination)
    return manifest


def restore(package: Path, root: Path, dry_run: bool = False) -> dict:
    """Validate the whole package before presenting an entirely new workspace."""
    try:
        requested = root.expanduser()
        if requested.exists() or requested.is_symlink():
            raise KnowledgeError("Restore requires a new directory; existing workspaces are never overwritten")
        root, package = requested.resolve(), package.expanduser().resolve()
        _outside_public_checkout(root)
        with tempfile.TemporaryDirectory(prefix="knowledge-verify-") as directory:
            verified = Path(directory)
            manifest = _validated_contents(package, verified)
            result = {"workspace": str(root), "restored": not dry_run, "dry_run": dry_run,
                      "files": len(manifest["files"]), "private_state": True,
                      "pending_recovery": (verified / ".knowledge/render-journal.json").exists(),
                      "next_steps": ["Run knowledge doctor for this workspace and review the configured source paths before syncing.",
                                     "Original sources, external attachments and Git/CLI authentication need separate restoration."]}
            if result["pending_recovery"]:
                result["next_steps"].append("Run knowledge build to validate and resume the saved render journal; restore did not execute it.")
            if dry_run:
                return result
            root.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".knowledge-restore-", dir=root.parent) as staging:
                staged_root = Path(staging) / "workspace"
                shutil.copytree(verified, staged_root, copy_function=shutil.copy2)
                if root.exists() or root.is_symlink():
                    raise KnowledgeError("Restore destination appeared during verification; choose a new directory")
                os.rename(staged_root, root)
            return result
    except (OSError, sqlite3.Error, ValueError, RuntimeError, zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise KnowledgeError("State package could not be verified or restored; the destination was not replaced") from exc
