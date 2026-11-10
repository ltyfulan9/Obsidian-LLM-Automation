"""Deterministic keyword search over explicit content fields, never serialized metadata."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .common import KnowledgeError

KINDS = {"markdown", "codex", "claude", "export", "checkin", "task"}


def _day(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("Non-canonical date")
    except ValueError as exc:
        raise KnowledgeError(f"Search {label} must be YYYY-MM-DD") from exc
    return value


def _snippet(value: str, terms: list[str], limit: int = 280) -> str:
    value = " ".join(value.split())
    folded = value.casefold()
    positions = [folded.find(term) for term in terms if term in folded]
    position = min(positions, default=0)
    if len(folded) != len(value):
        # Casefold can expand a character (for example ß); map the hit back to its original offset.
        length = 0
        for index, character in enumerate(value):
            length += len(character.casefold())
            if length > position:
                position = index
                break
    start = max(0, position - 80)
    prefix = "…" if start else ""
    size = limit - len(prefix)
    excerpt = value[start:start + size]
    if start + len(excerpt) < len(value):
        excerpt = excerpt[:size - 1] + "…"
    return prefix + excerpt


def search_catalog(rows: list[dict], personal: dict, query: str, *, since: str | None = None,
                   until: str | None = None, kind: str | None = None) -> list[dict]:
    """Match whitespace-separated keywords with AND; rank content fields before recency."""
    if not isinstance(query, str) or not query.strip():
        raise KnowledgeError("Search requires at least one keyword")
    terms = list(dict.fromkeys(query.casefold().split()))
    since, until = _day(since, "since"), _day(until, "until")
    if since and until and since > until:
        raise KnowledgeError("Search since must not be later than until")
    if kind is not None and (not isinstance(kind, str) or kind not in KINDS):
        raise KnowledgeError("Search kind must be markdown, codex, claude, export, checkin or task")

    def in_window(day: str) -> bool:
        return (since is None or day >= since) and (until is None or day <= until)

    results = []

    def add(result: dict, fields: dict[str, str]) -> None:
        folded = {name: value.casefold() for name, value in fields.items()}
        if not all(any(term in value for value in folded.values()) for term in terms):
            return
        matched = [name for name, value in folded.items() if any(term in value for term in terms)]
        score = tuple(sum(term in folded.get(name, "") for term in terms) for name in ("title", "topics", "summary"))
        structured = " ".join(value for name, value in folded.items() if name not in {"title", "topics", "summary", "body"})
        score += (sum(term in structured for term in terms), sum(term in folded.get("body", "") for term in terms))
        content_fields = [name for name in fields if name not in {"title", "topics"}]
        excerpt = next((fields[name] for name in content_fields if name in matched),
                       next((fields[name] for name in content_fields if fields[name]), fields["title"]))
        results.append((score, {**result, "snippet": _snippet(excerpt, terms), "matched_fields": matched}))

    for row in rows:
        document, summary = row["document"], row["summary"]
        if (kind is not None and document["kind"] != kind) or not in_window(document["day"]):
            continue
        fields = {"title": summary["title"], "topics": " ".join(summary["topics"]), "summary": summary["summary"],
                  **{name: " ".join(summary[name]) for name in ("key_points", "decisions", "questions")},
                  "body": document["text"]}
        add({"date": document["day"], "title": summary["title"], "topics": list(summary["topics"]),
             "file": f"Sources/{document['id']}.md", "kind": document["kind"], "source": document["source"],
             "method": summary.get("method") or "unknown", "available": bool(row["available"])}, fields)

    if kind in {None, "checkin"}:
        for entry in personal.get("checkins", []):
            if not in_window(entry["day"]):
                continue
            fields = {"title": "每日回填", **{name: " ".join(entry.get(name, [])) for name in ("done", "blocked", "lessons")}}
            add({"date": entry["day"], "title": fields["title"], "topics": [], "file": f"Daily/{entry['day']}.md#checkin",
                 "kind": "checkin", "source": "self", "method": "self-report", "available": True}, fields)

    if kind in {None, "task"}:
        events = defaultdict(list)
        for event in sorted(personal.get("events", []), key=lambda item: (item["day"], item.get("seq", 0))):
            if in_window(event["day"]):
                events[event["task_id"]].append(event)
        for task in personal.get("tasks", []):
            if until is not None and task["created"] > until:
                continue
            relevant = events[task["id"]]
            days = [event["day"] for event in relevant]
            if in_window(task["created"]):
                days.append(task["created"])
            if not days:
                continue
            fields = {"title": task["title"], "expected": task["expected"],
                      "outcome": " ".join(event.get("outcome", "") for event in relevant),
                      "reason": " ".join(event.get("reason", "") for event in relevant)}
            add({"date": max(days), "title": task["title"], "topics": [], "file": f"Tasks.md#task-{task['id']}",
                 "kind": "task", "source": "self", "method": "self-report", "available": True}, fields)

    # Stable tie-breaking does not depend on catalog input order.
    results.sort(key=lambda item: item[1]["file"])
    results.sort(key=lambda item: item[1]["date"], reverse=True)
    results.sort(key=lambda item: item[0], reverse=True)
    return [result for _, result in results[:50]]
