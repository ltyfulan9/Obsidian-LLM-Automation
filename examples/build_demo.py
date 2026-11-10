"""Rebuild the public example from invented sources, never from local CLI history."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from knowledge.common import read_json, write_json
from knowledge.service import initialize, sync
from knowledge.reflection import checkin, task


def main():
    example = Path(__file__).resolve().parent
    # Freeze only the synthetic example's calendar so checked-in pages are reproducible.
    with tempfile.TemporaryDirectory(prefix="knowledge-demo-") as directory, \
            patch("knowledge.reflection.current_day", return_value="2026-01-11"), \
            patch("knowledge.personal_render.current_day", return_value="2026-01-11"):
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
        prototype = task(root, "add", "交付虚构阅读工具原型", day="2026-01-05", due="2026-01-06",
                         expected="可以导入一份样本并展示搜索结果")["id"]
        task(root, "defer", prototype, day="2026-01-06", due="2026-01-08", reason="测试环境没有准备好")
        task(root, "defer", prototype, day="2026-01-08", due="2026-01-09", reason="样本格式需要再次确认")
        task(root, "finish", prototype, day="2026-01-10", outcome="样本导入与搜索验收通过，比最初约定晚 4 天")
        task(root, "add", "补写虚构工具的恢复说明", day="2026-01-05", due="2026-01-09",
             expected="一页能照着操作的说明")
        for day in ("2026-01-05", "2026-01-06", "2026-01-07"):
            checkin(root, day, ["完成一个小步骤"], ["等待测试环境"], ["下次先验证依赖，再承诺日期"])
        checkin(root, "2026-01-10", ["阅读工具原型通过验收"], [], ["把交付范围写成一条验收标准"])
        destination = example / "demo-wiki"
        generated = read_json(root / ".knowledge/generated.json")
        for relative in generated:
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / relative, output)
        guide = root / "Notes/README.md"
        if guide.exists():
            (destination / "Notes").mkdir(exist_ok=True)
            shutil.copyfile(guide, destination / "Notes/README.md")
        print(dict(result, generated_files=len(generated), synthetic_as_of="2026-01-11"))


if __name__ == "__main__":
    main()
