"""A single, inspectable description of collection and publication boundaries."""

from __future__ import annotations


def sync_scope(config: dict) -> dict:
    return {
        "sources": [{"name": source["name"], "kind": source["kind"], "since": source.get("since"),
                     "include": source.get("include", ["*"]), "exclude": source.get("exclude", [])}
                    for source in config["sources"]],
        "summary_engine": config["engine"]["name"],
        "publishes": ["Source summaries", "Daily journals", "Topic Wiki", "Timeline", "Mermaid maps",
                      "Obsidian Canvas", "Sync scope", "Handwritten Notes", "Daily self-reports",
                      "Confirmed commitments and outcomes", "Evidence-linked weekly reviews"],
        "raw_archive": bool(config.get("include_raw", False)),
        "local_only": ["Source text and operational personal state in SQLite", "Source paths and engine config", "Locks and run state"],
        "never_collected": ["API keys and login stores", "Hidden reasoning", "Tool outputs", "Magpie configuration backups"],
        "git_target": "Verified private GitHub repository only",
    }
