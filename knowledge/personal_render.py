"""Readable daily observations, commitment history and dated review evidence."""

from datetime import date, timedelta

from .reflection import current_day, report, snapshots


def inline(value: str) -> str:
    for character in "\\`*_{}[]<>()#|":
        value = value.replace(character, "\\" + character)
    return value.replace("\n", " ")


def bullets(values: list[str]) -> str:
    return "\n".join("- " + inline(value) for value in values) or "- 暂无回填。"


def daily_blocks(state: dict) -> dict[str, str]:
    pages = {}
    for entry in state.get("checkins", []):
        pages[entry["day"]] = (
            '<a id="checkin"></a>\n\n## 我的每日回填\n\n以下为本人记录，不代表外部核验。\n\n'
            + "### 已完成\n\n" + bullets(entry["done"]) + "\n\n"
            + "### 阻碍\n\n" + bullets(entry["blocked"]) + "\n\n"
            + "### 教训与下次尝试\n\n" + bullets(entry["lessons"]) + "\n\n")
    titles = {task["id"]: task["title"] for task in state.get("tasks", [])}
    for event in state.get("events", []):
        day = event["day"]
        if "## 承诺变更" not in pages.get(day, ""):
            pages[day] = pages.get(day, "") + "## 承诺变更\n\n"
        pages[day] += (f"- [{inline(titles[event['task_id']])}](../Tasks.md#event-{event['seq']})"
                       f" · {event_label(event)}\n")
    return {day: page.rstrip() + "\n\n" for day, page in pages.items()}


def event_label(event: dict) -> str:
    names = {"add": "确认承诺", "defer": "改期", "finish": "完成", "cancel": "取消", "reopen": "重新打开"}
    value = names[event["kind"]]
    if event.get("due"):
        value += "，截止 " + event["due"]
    if event.get("previous_due"):
        value += "（原截止 " + event["previous_due"] + "）"
    detail = event.get("outcome", event.get("reason", ""))
    return value + ("：" + inline(detail) if detail else "")


def evidence_link(value: str, prefix: str) -> str:
    if value.startswith("task:"):
        return f"[承诺 {value[5:]}]({prefix}Tasks.md#task-{value[5:]})"
    if value.startswith("event:"):
        seq, day = value[6:].split("@")
        return f"[{day} 变更 #{seq}]({prefix}Tasks.md#event-{seq})"
    if value.startswith("checkin:"):
        day = value[8:]
        return f"[{day} 回填]({prefix}Daily/{day}.md#checkin)"
    if value.startswith("due:"):
        return "记录截止：" + value[4:]
    return inline(value)


def review_page(result: dict, prefix: str = "") -> str:
    metrics = result["metrics"]
    page = f"# 行为复盘 · 截至 {result['as_of']}\n\n"
    page += f"[首页]({prefix}Home.md) · [承诺与结果]({prefix}Tasks.md)\n\n"
    page += result["limits"] + "\n\n"
    page += f"## 最近 7 天（{result['window_start']} 至 {result['as_of']}）\n\n"
    page += "| 记录指标 | 数量 |\n| --- | --- |\n"
    labels = {"recorded_days": "有每日回填的天数", "unobserved_days": "没有每日回填的天数（未知）",
              "new_commitments": "新增确认承诺", "completed": "已记录完成的承诺",
              "open_commitments": "截至当日仍打开的承诺（含更早）", "overdue": "已过截止且仍打开的承诺"}
    page += "\n".join(f"| {label} | {metrics[key]} |" for key, label in labels.items()) + "\n\n"
    page += "## 做成了什么\n\n"
    page += "### 完成的确认承诺\n\n"
    completed = result.get("completed_tasks", [])
    for task in completed:
        page += f"- [{task['day']} · {inline(task['title'])}]({prefix}Tasks.md#event-{task['event']})\n"
        page += f"  - 预计结果：{inline(task['expected']) or '未填写'}\n  - 实际结果（本人回填）：{inline(task['outcome'])}\n"
    if not completed:
        page += "最近七天暂无当前状态为完成的承诺记录。\n"
    page += "\n### 每日回填\n\n"
    page += "\n".join(f"- [{win['day']}]({prefix}Daily/{win['day']}.md#checkin)：{inline(win['text'])}"
                      for win in result["wins"]) or "暂无完成事项回填；这不表示实际没有完成事项。"
    page += "\n\n## 需要核对的模式\n\n"
    page += f"改期与重复阻碍统计窗口：{result['pattern_window_start']} 至 {result['as_of']}。\n\n"
    if not result["findings"]:
        page += "现有记录没有触发规则；这不证明没有问题，也不代表人格评价。\n\n"
    for index, finding in enumerate(result["findings"], 1):
        page += f"### {index}. {inline(finding['fact'])}\n\n"
        page += "- 记录依据：" + " · ".join(evidence_link(value, prefix) for value in finding["evidence"]) + "\n"
        page += "- 待核对：" + finding["question"] + "\n"
        page += "- 可选的小实验：" + finding["experiment"] + "\n\n"
    page += ("## 下一轮怎么验证\n\n选择一项你认同的改进，写入明确承诺与预计结果；"
             "执行后回填实际结果。下次比较预计和实际，而不是把建议当成已经改变。\n")
    return page


def projections(state: dict, config: dict) -> dict[str, str]:
    today = current_day(config)
    page = "# 我的承诺与结果\n\n[首页](Home.md) · [行为复盘](Review.md)\n\n"
    page += "仅列出你通过 task 命令确认的承诺。AI 提出的待办与问题仍保留在来源卡片，不会自动算作你的承诺。\n\n"
    labels = {"open": "未完成", "done": "已完成（本人回填）", "cancelled": "已取消"}
    tasks = snapshots(state, today)
    if not tasks:
        page += "尚未确认承诺。\n"
    for task in tasks:
        page += f"<a id=\"task-{task['id']}\"></a>\n\n## {inline(task['title'])}\n\n"
        page += f"- ID：`{task['id']}`\n- 确认日期：{task['created']}\n- 状态：{labels[task['status']]}\n"
        page += f"- 截止：{task['due'] or '未设置'}\n- 预计结果：{inline(task['expected']) or '未填写'}\n"
        page += f"- 实际结果 / 关闭原因：{inline(task['outcome']) or '尚未回填'}\n"
        if task.get("source_id"):
            page += f"- 起源：[来源卡片](Sources/{task['source_id']}.md)\n"
        page += "\n### 变更记录\n\n"
        for event in state.get("events", []):
            if event["task_id"] == task["id"] and event["day"] <= today:
                page += f"<a id=\"event-{event['seq']}\"></a>\n\n- {event['day']} · {event_label(event)}\n\n"
    files = {"Tasks.md": page, "Review.md": review_page(report(state, today))}
    days = {entry["day"] for entry in state.get("checkins", [])}
    days.update(event["day"] for event in state.get("events", []))
    days.add(today)
    weeks = {date.fromisoformat(day) - timedelta(days=date.fromisoformat(day).weekday()) for day in days if day <= today}
    links = []
    for monday in sorted(weeks, reverse=True):
        year, week, _ = monday.isocalendar()
        key = f"{year}-W{week:02d}"
        cutoff = min(today, (monday + timedelta(days=6)).isoformat())
        files[f"Reviews/{key}.md"] = review_page(report(state, cutoff), "../")
        links.append(f"- [{key}](Reviews/{key}.md) · 截至 {cutoff}")
    files["Review.md"] += "\n## 按周回看\n\n" + "\n".join(links) + "\n"
    return files
