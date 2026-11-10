"""Git publication is separate from local collection and always requires a private target."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .common import KnowledgeError, SECRET, read_json


def run(arguments: list[str], root: Path, timeout: int = 60) -> str:
    try:
        result = subprocess.run(arguments, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KnowledgeError(f"Command unavailable or timed out: {Path(arguments[0]).name}") from exc
    if result.returncode:
        raise KnowledgeError(f"Command failed: {Path(arguments[0]).name}; inspect authentication/network separately")
    return result.stdout.strip()


def private_target(root: Path) -> str:
    if not shutil.which("git") or not shutil.which("gh"):
        raise KnowledgeError("Publishing requires Git and authenticated GitHub CLI")
    top = Path(run(["git", "rev-parse", "--show-toplevel"], root)).resolve()
    if top != root.resolve():
        raise KnowledgeError("The knowledge workspace must be the Git repository root")
    branch = run(["git", "branch", "--show-current"], root)
    if branch != "main":
        raise KnowledgeError("Private knowledge publication requires the main branch")
    remote = run(["git", "remote", "get-url", "origin"], root)
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", remote)
    if not match:
        raise KnowledgeError("Origin must be a GitHub URL without embedded credentials")
    repository = match.group(1)
    visibility = run(["gh", "api", "--hostname", "github.com", f"repos/{repository}", "--jq", ".private"], root)
    if visibility != "true":
        raise KnowledgeError("Target is public or privacy cannot be verified; refusing publication")
    return repository


def publish(root: Path, include_raw: bool = False) -> str:
    private_target(root)
    if run(["git", "diff", "--cached", "--name-only"], root):
        raise KnowledgeError("Existing staged changes must be handled before knowledge publication")
    tracked_state = run(["git", "ls-files", "--", ".knowledge", ".env"], root)
    if tracked_state:
        raise KnowledgeError("Local state or credentials are already tracked; remove them from Git before publishing")
    registry = read_json(root / ".knowledge" / "generated.json")
    paths = sorted(path for path in registry if include_raw or not path.startswith("Archive/"))
    # Stage removed generated files too, including archives disabled by configuration.
    deleted = run(["git", "ls-files", "--deleted", "-z"], root).split("\0")
    paths += [path for path in deleted if path and (path.startswith(("Sources/", "Daily/", "Wiki/", "Maps/", "Archive/", "Reviews/"))
                                                    or path in {"Home.md", "Timeline.md", "Sync.md", "Tasks.md", "Review.md"}) and path not in paths]
    if (root / "Notes").exists():
        paths.append("Notes")
    paths += [".gitignore"] if (root / ".gitignore").exists() else []
    if paths:
        run(["git", "add", "--", *paths], root)
    staged = run(["git", "diff", "--cached", "--name-only", "-z"], root).split("\0")
    for path in filter(None, staged):
        if path not in paths and not path.startswith("Notes/"):
            raise KnowledgeError("Unexpected staged file; inspect the staging area")
    # Scan added content, not removed lines (which can include retired secrets).
    diff = run(["git", "diff", "--cached", "--no-ext-diff", "--unified=0"], root)
    added = "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    if SECRET.search(added):
        raise KnowledgeError("Secret-like content in staged changes; publication stopped")
    # Raw Markdown may legitimately contain hard-line-break spaces or blank endings.
    run(["git", "diff", "--cached", "--check", "--", ".", ":!Archive/**"], root)
    if any(staged):
        run(["git", "commit", "-m", "knowledge: update daily notes, topic wiki and maps"], root)
    # Check again immediately before transmission.
    private_target(root)
    run(["git", "push", "origin", "main"], root)
    return run(["git", "rev-parse", "HEAD"], root)
