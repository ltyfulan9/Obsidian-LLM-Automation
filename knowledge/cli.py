"""Cross-platform command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from .common import KnowledgeError, atomic_write, get_timezone, read_json, workspace_lock, write_json
from .publish import publish
from .schedule import definition
from .service import export_magpie, initialize, load_config, rebuild, search, sync
from .scope import sync_scope


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="knowledge", description="Notes and AI conversations → personal wiki, daily notes and maps")
    cli.add_argument("--version", action="version", version=__version__)
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("init", "sync", "build", "search", "status", "plan", "export-magpie", "schedule", "publish", "source"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", type=Path, required=True)
        if name == "sync":
            command.add_argument("--engine", choices=("extract", "codex", "claude"))
            command.add_argument("--push", action="store_true")
            command.add_argument("--magpie", action="store_true")
        elif name == "search":
            command.add_argument("query")
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
    try:
        if args.command == "init":
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
                # Validate before replacing the persisted configuration.
                import re
                if not re.fullmatch(r"[\w\-]{1,60}", args.name):
                    raise KnowledgeError("Use letters, numbers, underscores or hyphens in source names")
                write_json(root / ".knowledge" / "config.json", config)
                result = {"added": args.name, "kind": args.kind}
        elif args.command == "sync":
            result = sync(root, args.engine, args.push, args.magpie)
        elif args.command == "export-magpie":
            result = export_magpie(root, args.output.expanduser().resolve())
        elif args.command == "build":
            result = {"generated_files": rebuild(root)}
        elif args.command == "search":
            result = search(root, args.query)
        elif args.command == "status":
            config = load_config(root)
            latest = root / ".knowledge" / "last-run.json"
            result = {"sources": [{"name": s["name"], "kind": s["kind"]} for s in config["sources"]],
                      "engine": config["engine"]["name"], "last_run": read_json(latest) if latest.exists() else None}
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
        print(f"knowledge: {exc}", file=sys.stderr)
        return 1
