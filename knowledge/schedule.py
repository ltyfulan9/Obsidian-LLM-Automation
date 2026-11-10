"""Generate native scheduler definitions without installing a background job implicitly."""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from .common import KnowledgeError


def definition(root: Path, platform: str, hour: int, minute: int, push: bool = False, python: str | None = None,
               interval_minutes: int | None = None, magpie: bool = False) -> str:
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise KnowledgeError("Schedule time must be a valid hour and minute")
    if interval_minutes is not None and not 5 <= interval_minutes <= 1440:
        raise KnowledgeError("Schedule interval must be between 5 and 1440 minutes")
    args = [python or sys.executable, "-m", "knowledge", "sync", "--workspace", str(root), "--log"]
    if push:
        args.append("--push")
    if magpie:
        args.append("--magpie")
    if platform == "macos":
        payload = {
            "Label": "io.personal.knowledge.daily",
            "ProgramArguments": args,
            "WorkingDirectory": str(root),
            "StandardOutPath": str(root / ".knowledge" / "scheduler.out.log"),
            "StandardErrorPath": str(root / ".knowledge" / "scheduler.err.log"),
            "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        }
        if interval_minutes is not None:
            payload.update({"StartInterval": interval_minutes * 60, "RunAtLoad": True})
        else:
            payload["StartCalendarInterval"] = {"Hour": hour, "Minute": minute}
        return plistlib.dumps(payload, sort_keys=False).decode("utf-8")
    if platform != "windows":
        raise KnowledgeError("Unknown scheduler platform")
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)
    task = ET.Element("Task", {"version": "1.2", "xmlns": ns})
    triggers = ET.SubElement(task, "Triggers")
    trigger = ET.SubElement(triggers, "TimeTrigger" if interval_minutes is not None else "CalendarTrigger")
    if interval_minutes is not None:
        repetition = ET.SubElement(trigger, "Repetition")
        ET.SubElement(repetition, "Interval").text = f"PT{interval_minutes}M"
    ET.SubElement(trigger, "StartBoundary").text = f"2020-01-01T{hour:02}:{minute:02}:00"
    ET.SubElement(trigger, "Enabled").text = "true"
    if interval_minutes is None:
        daily = ET.SubElement(trigger, "ScheduleByDay")
        ET.SubElement(daily, "DaysInterval").text = "1"
    settings = ET.SubElement(task, "Settings")
    ET.SubElement(settings, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, "StartWhenAvailable").text = "true"
    ET.SubElement(settings, "DisallowStartIfOnBatteries").text = "false"
    ET.SubElement(settings, "StopIfGoingOnBatteries").text = "false"
    actions = ET.SubElement(task, "Actions")
    execute = ET.SubElement(actions, "Exec")
    ET.SubElement(execute, "Command").text = args[0]
    ET.SubElement(execute, "Arguments").text = subprocess.list2cmdline(args[1:])
    ET.SubElement(execute, "WorkingDirectory").text = str(root)
    ET.indent(task)
    # No encoding declaration: valid UTF-8 on disk and valid when PowerShell passes
    # the document to Task Scheduler as an in-memory UTF-16 COM string.
    return '<?xml version="1.0"?>\n' + ET.tostring(task, encoding="unicode") + "\n"
