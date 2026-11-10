"""User-confirmed observations and commitments, with evidence-based review rules."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from .catalog import Catalog
from .common import KnowledgeError, clean_text, digest, get_timezone, workspace_lock


def current_day(config: dict) -> str:
    return datetime.now().astimezone(get_timezone(config.get("timezone", "local"))).date().isoformat()


def valid_day(value: str) -> str:
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Non-canonical date")
    except (ValueError, TypeError) as exc:
        raise KnowledgeError("Use a date in YYYY-MM-DD format") from exc
    return value


def text(value: str, config: dict, required: bool = True) -> str:
    value = clean_text(value.strip(), config.get("privacy", {}))
    if (required and not value) or len(value) > 2000:
        raise KnowledgeError("Personal entries require nonempty text of at most 2000 characters")
    return value


def snapshots(state: dict, as_of: str) -> list[dict]:
    tasks = {task["id"]: dict(task, status="open", due=None, outcome="", closed=None, deferrals=0)
             for task in state.get("tasks", []) if task["created"] <= as_of}
    for event in sorted(state.get("events", []), key=lambda event: (event["day"], event["seq"])):
        if event["day"] > as_of or event["task_id"] not in tasks:
            continue
        task = tasks[event["task_id"]]
        if event["kind"] in {"add", "defer"}:
            task["due"] = event.get("due")
            task["deferrals"] += int(event["kind"] == "defer")
        elif event["kind"] in {"finish", "cancel"}:
            task["status"] = "done" if event["kind"] == "finish" else "cancelled"
            task["outcome"] = event.get("outcome", event.get("reason", ""))
            task["closed"] = event["day"]
        elif event["kind"] == "reopen":
            task.update(status="open", outcome="", closed=None)
    return list(tasks.values())


def report(state: dict, as_of: str) -> dict:
    valid_day(as_of)
    start = (date.fromisoformat(as_of) - timedelta(days=6)).isoformat()
    pattern_start = (date.fromisoformat(as_of) - timedelta(days=27)).isoformat()
    tasks = snapshots(state, as_of)
    checkins = [entry for entry in state.get("checkins", []) if start <= entry["day"] <= as_of]
    overdue = [task for task in tasks if task["status"] == "open" and task["due"] and task["due"] < as_of]
    findings = []
    for task in overdue:
        findings.append({"kind": "overdue", "fact": f"任务「{task['title']}」已过记录的截止日期，状态仍为未完成。",
                         "evidence": [f"task:{task['id']}", f"due:{task['due']}"],
                         "question": "实际已做完但忘记回填，还是需要重新安排？",
                         "experiment": "核对现实结果后，完成回填、说明取消原因，或拆出一个更小的下一步。"})
    deferred = defaultdict(list)
    blockers = defaultdict(set)
    for event in state.get("events", []):
        if event["kind"] == "defer" and pattern_start <= event["day"] <= as_of:
            deferred[event["task_id"]].append(event)
    for task_id, events in deferred.items():
        if len(events) >= 2:
            task = next(task for task in tasks if task["id"] == task_id)
            findings.append({"kind": "repeated_deferral", "fact": f"任务「{task['title']}」近 28 天记录了 {len(events)} 次改期。",
                             "evidence": [f"event:{event['seq']}@{event['day']}" for event in events],
                             "question": "是任务范围、时间估计或外部依赖发生了变化？现有记录不足以确定原因。",
                             "experiment": "下次承诺前写明最小交付物与前置条件，再比较预计和实际结果。"})
    for entry in state.get("checkins", []):
        if pattern_start <= entry["day"] <= as_of:
            for blocker in entry.get("blocked", []):
                blockers[blocker].add(entry["day"])
    for blocker, days in blockers.items():
        if len(days) >= 3:
            findings.append({"kind": "repeated_blocker", "fact": f"同一项自报阻碍「{blocker}」在近 28 天的 {len(days)} 天出现。",
                             "evidence": [f"checkin:{day}" for day in sorted(days)],
                             "question": "这些记录是否确实是同一个原因？这里只按相同文字归组。",
                             "experiment": "选择一个你能改变的条件试行一周，用后续回填验证阻碍是否减少。"})
    return {"as_of": as_of, "window_start": start, "pattern_window_start": pattern_start,
            "metrics": {"recorded_days": len(checkins), "unobserved_days": 7 - len(checkins),
                        "new_commitments": sum(start <= task["created"] <= as_of for task in tasks),
                        "completed": sum(task["status"] == "done" and start <= task["closed"] <= as_of for task in tasks),
                        "open_commitments": sum(task["status"] == "open" for task in tasks), "overdue": len(overdue)},
            "wins": [{"day": entry["day"], "text": value} for entry in checkins for value in entry.get("done", [])],
            "findings": findings,
            "limits": "依据用户回填与确认的任务；未记录不等于未完成。没有人格评分、诊断或因果结论。"}


def refresh(root: Path, catalog: Catalog, config: dict) -> None:
    from .render import build
    from .service import ensure_notes_guide
    try:
        ensure_notes_guide(root)
        build(root, catalog.rows(), config, catalog.personal_state())
    except (KnowledgeError, OSError) as exc:
        raise KnowledgeError("Personal record saved locally, but pages could not be refreshed. "
                             "Resolve generated-page conflicts, then run knowledge build.") from exc


def checkin(root: Path, day: str | None, done: list[str], blocked: list[str], lessons: list[str], replace: bool = False) -> dict:
    from .service import load_config
    config = load_config(root)
    day = valid_day(day or current_day(config))
    if day > current_day(config):
        raise KnowledgeError("A daily observation cannot be recorded as a future result")
    if not any((done, blocked, lessons)):
        raise KnowledgeError("Provide at least one completed item, blocker or lesson")
    values = {key: [text(value, config) for value in items] for key, items in (("done", done), ("blocked", blocked), ("lessons", lessons))}
    with workspace_lock(root):
        catalog = Catalog(root)
        try:
            previous = catalog.connection.execute("SELECT data FROM checkins WHERE day = ?", (day,)).fetchone()
            old = json.loads(previous["data"]) if previous and not replace else {}
            data = {key: list(dict.fromkeys(old.get(key, []) + values[key])) for key in values}
            with catalog.connection:
                catalog.connection.execute("INSERT INTO checkins VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET data=excluded.data",
                                           (day, json.dumps(data, ensure_ascii=False)))
            refresh(root, catalog, config)
            return {"date": day, **data, "file": f"Daily/{day}.md"}
        finally:
            catalog.close()


def task(root: Path, action: str, value: str | None = None, *, day: str | None = None, due: str | None = None,
         expected: str = "", outcome: str = "", reason: str = "", source_id: str | None = None) -> dict | list:
    from .service import load_config
    config = load_config(root)
    day = valid_day(day or current_day(config))
    if due is not None:
        valid_day(due)
    with workspace_lock(root):
        catalog = Catalog(root)
        try:
            state = catalog.personal_state()
            if action == "list":
                return snapshots(state, day)
            if day > current_day(config):
                raise KnowledgeError("Record actual task events on or before today")
            if action == "add":
                title = text(value or "", config)
                expected = text(expected, config, False)
                identifier = digest(day + "\0" + title)[:12]
                existing = next((item for item in state["tasks"] if item["id"] == identifier), None)
                if existing:
                    original = next(event for event in state["events"] if event["task_id"] == identifier and event["kind"] == "add")
                    if (existing["expected"], existing["source_id"], original["due"]) != (expected, source_id, due):
                        raise KnowledgeError("Same-day task already exists with different details; use its ID to change status or dates")
                    refresh(root, catalog, config)
                    return {"id": identifier, "already_recorded": True}
                if source_id and not catalog.current(source_id):
                    raise KnowledgeError("Task source must be an existing source-card ID")
                with catalog.connection:
                    catalog.connection.execute("INSERT INTO commitments VALUES (?, ?, ?, ?, ?)",
                                               (identifier, title, day, expected, source_id))
                    catalog.connection.execute("INSERT INTO commitment_events (task_id, day, kind, data) VALUES (?, ?, 'add', ?)",
                                               (identifier, day, json.dumps({"due": due})))
            else:
                identifier = value
                current = next((item for item in snapshots(state, "9999-12-31") if item["id"] == identifier), None)
                if not current:
                    raise KnowledgeError("Unknown task ID")
                latest = max(event["day"] for event in state["events"] if event["task_id"] == identifier)
                if day < latest:
                    raise KnowledgeError("An event cannot predate the task's latest recorded event")
                if action != "reopen" and current["status"] != "open":
                    raise KnowledgeError("Reopen a closed task before changing it")
                if action == "finish":
                    data = {"outcome": text(outcome, config)}
                elif action == "defer":
                    if not due or (current["due"] and due <= current["due"]):
                        raise KnowledgeError("A deferral needs a later due date")
                    data = {"due": due, "previous_due": current["due"], "reason": text(reason, config)}
                elif action in {"cancel", "reopen"}:
                    if action == "reopen" and current["status"] == "open":
                        raise KnowledgeError("Task is already open")
                    data = {"reason": text(reason, config)}
                else:
                    raise KnowledgeError("Unknown task action")
                with catalog.connection:
                    catalog.connection.execute("INSERT INTO commitment_events (task_id, day, kind, data) VALUES (?, ?, ?, ?)",
                                               (identifier, day, action, json.dumps(data, ensure_ascii=False)))
            refresh(root, catalog, config)
            return {"id": identifier, "action": action, "date": day, "file": "Tasks.md"}
        finally:
            catalog.close()


def review(root: Path, as_of: str | None = None) -> dict:
    from .service import load_config
    config = load_config(root)
    as_of = valid_day(as_of or current_day(config))
    catalog = Catalog(root)
    try:
        return report(catalog.personal_state(), as_of)
    finally:
        catalog.close()
