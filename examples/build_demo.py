"""Rebuild the public example from invented sources, never from local CLI history."""

import shutil
import tempfile
from pathlib import Path

from knowledge.common import read_json, write_json
from knowledge.service import initialize, sync


def main():
    example = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="knowledge-demo-") as directory:
        root = Path(directory) / "wiki"
        initialize(root)
        config = read_json(root / ".knowledge/config.json")
        config["timezone"] = "+08:00"
        config["sources"] = [
            {"name": "demo-notes", "kind": "markdown", "path": str(example / "inputs/notes")},
            {"name": "demo-codex", "kind": "codex", "path": str(example / "inputs/codex"), "since": "2026-01-01"},
            {"name": "demo-claude", "kind": "claude", "path": str(example / "inputs/claude"), "since": "2026-01-01"},
        ]
        write_json(root / ".knowledge/config.json", config)
        result = sync(root)
        destination = example / "demo-wiki"
        for relative in read_json(root / ".knowledge/generated.json"):
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / relative, output)
        print(result)


if __name__ == "__main__":
    main()
