"""Generate native scheduler definitions without installing a background job implicitly."""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from .common import KnowledgeError


def definition(root: Path, platform: str, hour: int, minute: int, push: bool = False, python: str | None = None) -> str:
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise KnowledgeError("Schedule time must be a valid hour and minute")
    args = [python or sys.executable, "-m", "knowledge", "sync", "--workspace", str(root)]
    if push:
        args.append("--push")
    if platform == "macos":
        return plistlib.dumps({
            "Label": "io.personal.knowledge.daily",
            "ProgramArguments": args,
            "StartCalendarInterval": {"Hour": hour, "Minute": minute},
            "WorkingDirectory": str(root),
            "StandardOutPath": str(root / ".knowledge" / "scheduler.out.log"),
            "StandardErrorPath": str(root / ".knowledge" / "scheduler.err.log"),
            "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        }, sort_keys=False).decode("utf-8")
    if platform != "windows":
        raise KnowledgeError("Unknown scheduler platform")
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)
    task = ET.Element("Task", {"version": "1.2", "xmlns": ns})
    triggers = ET.SubElement(task, "Triggers")
    trigger = ET.SubElement(triggers, "CalendarTrigger")
    ET.SubElement(trigger, "StartBoundary").text = f"2020-01-01T{hour:02}:{minute:02}:00"
    ET.SubElement(trigger, "Enabled").text = "true"
    daily = ET.SubElement(trigger, "ScheduleByDay")
    ET.SubElement(daily, "DaysInterval").text = "1"
    settings = ET.SubElement(task, "Settings")
    ET.SubElement(settings, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, "StartWhenAvailable").text = "true"
    actions = ET.SubElement(task, "Actions")
    execute = ET.SubElement(actions, "Exec")
    ET.SubElement(execute, "Command").text = args[0]
    ET.SubElement(execute, "Arguments").text = subprocess.list2cmdline(args[1:])
    ET.SubElement(execute, "WorkingDirectory").text = str(root)
    ET.indent(task)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(task, encoding="unicode") + "\n"
