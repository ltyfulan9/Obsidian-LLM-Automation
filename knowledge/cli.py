"""Cross-platform command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from .common import KnowledgeError, atomic_write, get_timezone, read_json, workspace_lock, write_json
from .publish import publish
from .schedule import definition
from .service import export_magpie, initialize, load_config, rebuild, search, sync
from .scope import sync_scope
from .reflection import checkin, review, task


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="knowledge", description="Notes and AI conversations → personal wiki, daily notes and maps")
    cli.add_argument("--version", action="version", version=__version__)
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("init", "sync", "build", "search", "status", "plan", "export-magpie", "schedule", "publish", "source", "checkin", "task", "review", "demo", "doctor", "backup", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", type=Path, required=True)
        if name == "backup":
            command.add_argument("--output", type=Path, required=True)
        elif name == "restore":
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--dry-run", action="store_true")
        elif name == "status":
            command.add_argument("--format", choices=("text", "json"), default="json")
        elif name == "doctor":
            command.add_argument("--publish", action="store_true", help="Explicitly check the private GitHub publication target")
            command.add_argument("--format", choices=("text", "json"), default="text")
        elif name == "checkin":
            command.add_argument("--date")
            command.add_argument("--done", action="append", default=[])
            command.add_argument("--blocked", action="append", default=[])
            command.add_argument("--lesson", action="append", default=[])
            command.add_argument("--replace", action="store_true")
        elif name == "task":
            command.add_argument("action", choices=("add", "list", "finish", "defer", "cancel", "reopen"))
            command.add_argument("value", nargs="?", help="Title for add, task ID for other changes")
            command.add_argument("--date")
            command.add_argument("--due")
            command.add_argument("--expected", default="")
            command.add_argument("--outcome", default="")
            command.add_argument("--reason", default="")
            command.add_argument("--source", help="Existing source-card ID")
            command.add_argument("--status", choices=("all", "open", "done", "cancelled"), default="all")
            command.add_argument("--overdue", action="store_true", help="List open commitments whose recorded due date has passed")
            command.add_argument("--format", choices=("text", "json"), default="json")
        elif name == "review":
            command.add_argument("--as-of")
        elif name == "sync":
            command.add_argument("--engine", choices=("extract", "codex", "claude"))
            command.add_argument("--push", action="store_true")
            command.add_argument("--magpie", action="store_true")
            command.add_argument("--log", action="store_true", help="Append safe metadata to .knowledge/scheduler.jsonl")
        elif name == "search":
            command.add_argument("query")
            command.add_argument("--since")
            command.add_argument("--until")
            command.add_argument("--kind", choices=("markdown", "codex", "claude", "export", "checkin", "task"))
            command.add_argument("--format", choices=("text", "json"), default="json")
        elif name == "schedule":
            command.add_argument("--platform", choices=("macos", "windows"), required=True)
            command.add_argument("--hour", type=int, default=21)
            command.add_argument("--minute", type=int, default=0)
            command.add_argument("--interval-minutes", type=int)
            command.add_argument("--push", action="store_true")
            command.add_argument("--magpie", action="store_true")
            command.add_argument("--python", help="Absolute interpreter from the machine where the schedule will run")
            command.add_argument("--output", type=Path, required=True)
        elif name == "source":
            command.add_argument("kind", choices=("markdown", "codex", "claude", "export"))
            command.add_argument("path", type=Path)
            command.add_argument("--name", required=True)
            command.add_argument("--include", action="append")
            command.add_argument("--exclude", action="append")
            command.add_argument("--recent-days", type=int, help="First-import calendar-day window, persisted as a fixed since date")
        elif name == "export-magpie":
            command.add_argument("--output", type=Path, required=True)
    return cli


def main(argv=None) -> int:
    # Keep piped Chinese titles and JSON portable across Windows code pages.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    root = args.workspace.expanduser().resolve()
    operation_id = uuid.uuid4().hex if args.command == "sync" else None
    try:
        if args.command == "backup":
            from .backup import backup
            result = backup(root, args.output.expanduser().resolve())
        elif args.command == "restore":
            from .backup import restore
            result = restore(args.input.expanduser().resolve(), root, dry_run=args.dry_run)
        elif args.command == "doctor":
            from .doctor import doctor
            result = doctor(root, check_publish=args.publish)
            if args.format == "json":
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("Local workspace checks passed" if result["ok"] else "Local workspace needs attention")
                for check in result["checks"]:
                    print(f"[{check['status']}] {check['id']}: {check['message']}")
                    if check.get("next_step"):
                        print("  Next: " + check["next_step"])
            return 0 if result["ok"] else 1
        elif args.command == "demo":
            from .demo import create_demo
            result = create_demo(root)
        elif args.command == "init":
            initialize(root)
            result = {"workspace": str(root), "next": "Add explicit sources with knowledge source, then knowledge sync"}
        elif args.command == "source":
            with workspace_lock(root):
                config = load_config(root)
                if any(source["name"] == args.name for source in config["sources"]):
                    raise KnowledgeError("Source name already exists; edit the local config to change it")
                source = {"name": args.name, "kind": args.kind, "path": str(args.path.expanduser().resolve())}
                if args.include:
                    source["include"] = args.include
                if args.exclude:
                    source["exclude"] = args.exclude
                if args.recent_days is not None:
                    if args.recent_days <= 0:
                        raise KnowledgeError("recent-days must be positive")
                    today = datetime.now().astimezone(get_timezone(config.get("timezone", "local"))).date()
                    source["since"] = (today - timedelta(days=args.recent_days - 1)).isoformat()
                config["sources"].append(source)
                from .config import validate_config
                validate_config(config)
                write_json(root / ".knowledge" / "config.json", config)
                result = {"added": args.name, "kind": args.kind}
        elif args.command == "checkin":
            result = checkin(root, args.date, args.done, args.blocked, args.lesson, args.replace)
        elif args.command == "task":
            if args.action != "list" and (args.status != "all" or args.overdue or args.format != "json"):
                raise KnowledgeError("Task filters and text output apply to list only")
            result = task(root, args.action, args.value, day=args.date, due=args.due, expected=args.expected,
                          outcome=args.outcome, reason=args.reason, source_id=args.source)
            if args.action == "list":
                from .reflection import current_day
                day = args.date or current_day(load_config(root))
                result = [item for item in result if (args.status == "all" or item["status"] == args.status)
                          and (not args.overdue or item["status"] == "open" and item["due"] and item["due"] < day)]
                if args.format == "text":
                    print(f"确认承诺 · 截至 {day} · {len(result)} 项")
                    for item in result:
                        print(f"{item['id']}  {item['status']}  {item['title'].replace(chr(10), ' ')}")
                        print(f"  截止：{item['due'] or '未设置'} · 预计：{item['expected'] or '未填写'}")
                        if item["outcome"]:
                            print("  实际结果 / 关闭原因：" + item["outcome"].replace("\n", " "))
                    return 0
        elif args.command == "review":
            result = review(root, args.as_of)
        elif args.command == "sync":
            result = sync(root, args.engine, args.push, args.magpie, run_id=operation_id)
            if args.log:
                from .runstate import append_log
                append_log(root, result)
        elif args.command == "export-magpie":
            result = export_magpie(root, args.output.expanduser().resolve())
        elif args.command == "build":
            result = {"generated_files": rebuild(root)}
        elif args.command == "search":
            result = search(root, args.query, since=args.since, until=args.until, kind=args.kind)
            if args.format == "text":
                print(f"关键词匹配 · {len(result)} 条结果（最多 50 条）")
                labels = {"extract": "本地摘录", "codex": "AI 整理（codex CLI，待核实）", "claude": "AI 整理（claude CLI，待核实）", "self-report": "本人记录"}
                for item in result:
                    print(f"\n{item['date']}  {item['title']}")
                    print(f"  {item['source']} · {labels.get(item['method'], '整理方式未记录')} · 命中：{', '.join(item['matched_fields'])}")
                    if item["topics"]:
                        print("  主题：" + "、".join(item["topics"]))
                    if not item["available"]:
                        print("  来源状态：最近采集时不可访问，保留历史记录")
                    print("  " + item["snippet"])
                    print("  打开：" + item["file"])
                if not result:
                    print("未找到匹配记录；使用空格分开的关键词，所有关键词都必须匹配。")
                return 0
        elif args.command == "status":
            from .runstate import status
            result = status(root)
            if args.format == "text":
                attempt, success = result["last_attempt"], result["last_run"]
                print("最近同步尝试：" + ({"running": "记录为运行中", "succeeded": "已完成", "failed": "失败", "interrupted": "中断"}.get(attempt["status"], "未知") if attempt else "尚无记录"))
                if attempt:
                    phases = {"configuration": "配置校验", "verify_target": "私有目标核验", "verify_magpie": "Magpie 核验", "catalog": "打开目录数据库", "collect": "采集", "summarize": "整理", "render": "生成页面", "publish": "私有推送", "magpie": "Magpie 同步", "record": "保存运行记录", "complete": "完成"}
                    print("阶段：" + phases.get(attempt["phase"], "未知"))
                    saved = attempt.get("saved", {})
                    saved_names = {"catalog": "目录数据库", "rendered": "生成页面", "published": "GitHub 推送", "magpie": "Magpie 同步"}
                    print("本轮确认保存：" + ("、".join(title for key, title in saved_names.items() if saved.get(key)) or "尚未确认"))
                    if attempt.get("next_step"):
                        print("下一步：" + attempt["next_step"])
                print("最近完整成功：" + (str(success.get("time", "时间未记录")) if success else "尚无记录"))
                print("工作区锁：" + ("忙碌" if result["workspace_busy"] is True else "空闲" if result["workspace_busy"] is False else "无法确认"))
                if result["configuration_error"]:
                    print("配置需要修复：" + result["configuration_error"])
                print("后台任务是否已注册未在此查询；日志见 .knowledge/scheduler.jsonl。")
                return 0
        elif args.command == "plan":
            result = sync_scope(load_config(root))
        elif args.command == "schedule":
            load_config(root)
            output = args.output.expanduser().resolve()
            atomic_write(output, definition(root, args.platform, args.hour, args.minute, args.push, args.python, args.interval_minutes, args.magpie))
            result = {"schedule": str(output), "installed": False}
        else:
            config = load_config(root)
            with workspace_lock(root):
                result = {"published_commit": publish(root, config.get("include_raw", False))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (KnowledgeError, OSError, ValueError) as exc:
        # Raw provider responses and source bodies never enter the console error path.
        if args.command == "sync" and args.log:
            from .runstate import append_log
            try:
                append_log(root, run_id=operation_id)
            except OSError:
                pass
        print(f"knowledge: {exc}", file=sys.stderr)
        return 1
