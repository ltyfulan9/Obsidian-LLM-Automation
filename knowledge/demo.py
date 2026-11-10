"""An offline first-run journey using only small, invented records."""

from datetime import date, timedelta
from pathlib import Path

from .common import KnowledgeError, atomic_write, read_json, write_json
from .reflection import checkin, task
from .service import initialize, sync


def create_demo(root: Path) -> dict:
    root = root.expanduser().resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise KnowledgeError("Demo needs a new or empty directory; existing workspaces are never overwritten")
    initialize(root)
    today = date.today().isoformat()
    inputs = root / ".knowledge/demo-inputs"
    atomic_write(inputs / "notes/园艺计划.md", (
        f"---\ndate: {today}\ntags: [园艺, 学习记录]\n---\n\n# 虚构演示：阳台园艺\n\n"
        "这是一份虚构的园艺资料，用来体验知识库，不包含真实生活记录。\n\n"
        "先比较光照、浇水和记录方法，再制定小规模观察计划。\n"))
    write_json(inputs / "chats/观星讨论.json", {"id": "invented-stargazing", "messages": [
        {"role": "user", "timestamp": today + "T09:00:00", "content": "虚构演示：我想建立观星记录，该保存什么？"},
        {"role": "assistant", "timestamp": today + "T09:01:00", "content": "记录日期、地点代号、天气与观察结果，区分观察和猜测。这是演示内容。"},
    ]})
    config = read_json(root / ".knowledge/config.json")
    config["sources"] = [
        {"name": "demo-notes", "kind": "markdown", "path": str(inputs / "notes")},
        {"name": "demo-chat", "kind": "export", "path": str(inputs / "chats")},
    ]
    write_json(root / ".knowledge/config.json", config)
    result = sync(root)
    identifier = task(root, "add", "虚构演示：整理园艺观察表", due=(date.today() + timedelta(days=1)).isoformat(),
                      expected="表中包含光照、浇水和观察结果三个栏目")["id"]
    checkin(root, today, ["虚构演示：核对了两份示例资料"], [], ["这是试用工作区，可以整体保留供练习"])
    return {"workspace": str(root), "home": str(root / "Home.md"), "synthetic": True,
            "documents": result["documents"], "task_id": identifier,
            "next_steps": ["Open Home.md in Obsidian or a Markdown reader",
                           f"knowledge search --workspace \"{root}\" 园艺",
                           f"knowledge doctor --workspace \"{root}\""]}
