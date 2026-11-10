"""Recover interrupted multi-file generation without discarding manual edits."""

from pathlib import Path, PurePosixPath

from .common import KnowledgeError, atomic_write, digest, read_json, write_json

ROOT_FILES = {"Home.md", "Timeline.md", "Sync.md", "Tasks.md", "Review.md"}
MANAGED_DIRS = {"Sources", "Daily", "Wiki", "Maps", "Archive", "Reviews"}


def generated_area(relative: Path) -> bool:
    parts = relative.parts
    return bool(parts) and (parts[0].casefold() in {value.casefold() for value in MANAGED_DIRS}
                            or len(parts) == 1 and parts[0].casefold() in {value.casefold() for value in ROOT_FILES})


def target_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise KnowledgeError("Invalid generated path")
    parts = PurePosixPath(relative).parts
    allowed = relative in ROOT_FILES or (
        len(parts) == 2 and parts[0] in MANAGED_DIRS
        and parts[1] not in {".", ".."} and relative.endswith((".md", ".canvas")))
    target = root / relative
    if not allowed or not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
        raise KnowledgeError("Generated path is outside the managed boundary")
    return target


def registry(root: Path) -> dict:
    path = root / ".knowledge/generated.json"
    values = read_json(path) if path.exists() else {}
    if not isinstance(values, dict):
        raise KnowledgeError("Invalid generated registry")
    for relative, value in values.items():
        target_path(root, relative)
        if not isinstance(value, str) or len(value) != 64:
            raise KnowledgeError("Invalid generated registry hash")
    return values


def recover(root: Path) -> None:
    path = root / ".knowledge/render-journal.json"
    if not path.exists():
        return
    journal = read_json(path)
    if not isinstance(journal, dict) or set(journal) != {"writes", "deletes", "manifest"}:
        raise KnowledgeError("Invalid render recovery journal")
    writes, deletes, manifest = journal["writes"], journal["deletes"], journal["manifest"]
    if not all(isinstance(value, dict) for value in (writes, deletes, manifest)):
        raise KnowledgeError("Invalid render recovery operations")
    # Validate the whole operation before modifying any page.
    for relative, operation in writes.items():
        target = target_path(root, relative)
        if not isinstance(operation, dict) or not isinstance(operation.get("text"), str):
            raise KnowledgeError("Invalid render recovery content")
        new = digest(operation["text"])
        if manifest.get(relative) != new:
            raise KnowledgeError("Render recovery hash mismatch")
        current = digest(target.read_text(encoding="utf-8")) if target.exists() else None
        if current not in {None, operation.get("old"), new}:
            raise KnowledgeError(f"Manual edit conflicts with interrupted generation: {relative}")
    for relative, old in deletes.items():
        target = target_path(root, relative)
        if target.exists() and digest(target.read_text(encoding="utf-8")) != old:
            raise KnowledgeError(f"Manual edit conflicts with pending removal: {relative}")
    if set(manifest) != set(writes):
        raise KnowledgeError("Render recovery manifest mismatch")
    for relative, operation in writes.items():
        target = target_path(root, relative)
        if not target.exists() or digest(target.read_text(encoding="utf-8")) != manifest[relative]:
            atomic_write(target, operation["text"])
    for relative in deletes:
        target_path(root, relative).unlink(missing_ok=True)
    write_json(root / ".knowledge/generated.json", manifest)
    path.unlink()


def commit(root: Path, contents: dict[str, str]) -> int:
    recover(root)
    previous = registry(root)
    for relative in set(previous) | set(contents):
        target = target_path(root, relative)
        if target.exists() and (relative not in previous or digest(target.read_text(encoding="utf-8")) != previous[relative]):
            raise KnowledgeError(f"Generated file has manual changes; move the edits to Notes/ first: {relative}")
    manifest = {relative: digest(text) for relative, text in contents.items()}
    journal = {
        "writes": {relative: {"old": previous.get(relative), "text": text} for relative, text in contents.items()},
        "deletes": {relative: previous[relative] for relative in previous.keys() - contents.keys()},
        "manifest": manifest,
    }
    write_json(root / ".knowledge/render-journal.json", journal)
    recover(root)
    return len(manifest)
