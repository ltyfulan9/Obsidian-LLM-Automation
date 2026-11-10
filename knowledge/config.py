"""Validate configuration values without reading sources or modifying the input."""

from __future__ import annotations

import re
from datetime import date

from .common import KnowledgeError, get_timezone


def _integer(value: object, label: str, minimum: int = 1, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        limit = f"{minimum}..{maximum}" if maximum is not None else f"at least {minimum}"
        raise KnowledgeError(f"Config {label} must be an integer {limit}")


def _string(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise KnowledgeError(f"Config {label} must be a nonempty string")


def validate_config(config: object) -> dict:
    """Return a valid config unchanged, or raise a safe, field-specific error."""
    if not isinstance(config, dict):
        raise KnowledgeError("Config must be an object")
    if type(config.get("version")) is not int or config["version"] != 2:
        raise KnowledgeError("Unsupported config version; expected version 2")
    engine = config.get("engine")
    if not isinstance(engine, dict):
        raise KnowledgeError("Config engine must be an object")
    if not isinstance(engine.get("name"), str) or engine["name"] not in {"extract", "codex", "claude"}:
        raise KnowledgeError("Config engine.name must be extract, codex or claude")
    for key, default in (("timeout_seconds", 180), ("chunk_chars", 16000)):
        _integer(engine.get(key, default), "engine." + key)
    if "retries" in engine:
        _integer(engine["retries"], "engine.retries", 0, 3)
    for key in ("model", "command"):
        if engine.get(key) is not None:
            _string(engine[key], "engine." + key)

    timezone = config.get("timezone", "local")
    _string(timezone, "timezone")
    try:
        get_timezone(timezone)
    except (ValueError, TypeError) as exc:
        raise KnowledgeError("Config timezone must be local, UTC, an offset or an available IANA timezone") from exc
    privacy = config.get("privacy", {})
    if not isinstance(privacy, dict):
        raise KnowledgeError("Config privacy must be an object")
    for key in ("redact_local_paths", "redact_emails"):
        if key in privacy and type(privacy[key]) is not bool:
            raise KnowledgeError(f"Config privacy.{key} must be a boolean")
    for key, default in (("graph_max_documents", 120), ("max_file_bytes", 33554432)):
        _integer(config.get(key, default), key)
    if type(config.get("include_raw", False)) is not bool:
        raise KnowledgeError("Config include_raw must be a boolean")

    sources = config.get("sources")
    if not isinstance(sources, list):
        raise KnowledgeError("Config sources must be a list")
    names = set()
    for index, source in enumerate(sources):
        field = f"sources[{index}]"
        if not isinstance(source, dict):
            raise KnowledgeError(f"Config {field} must be an object")
        kind = source.get("kind")
        if not isinstance(kind, str) or kind not in {"markdown", "codex", "claude", "export"}:
            raise KnowledgeError(f"Config {field}.kind must be markdown, codex, claude or export")
        _string(source.get("path"), field + ".path")
        name = source.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[\w\-]{1,60}", name):
            raise KnowledgeError(f"Config {field}.name must contain 1..60 letters, numbers, underscores or hyphens")
        if name in names:
            raise KnowledgeError(f"Config {field}.name must be unique")
        names.add(name)
        if "since" in source:
            value = source["since"]
            try:
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError("Non-canonical date")
            except ValueError as exc:
                raise KnowledgeError(f"Config {field}.since must be YYYY-MM-DD") from exc
        for key in ("include", "exclude"):
            if key in source and (not isinstance(source[key], list) or any(not isinstance(value, str) for value in source[key])):
                raise KnowledgeError(f"Config {field}.{key} must be a list of strings")

    if "magpie" in config:
        magpie = config["magpie"]
        if not isinstance(magpie, dict):
            raise KnowledgeError("Config magpie must be an object")
        for key in ("executable", "data_dir"):
            if key in magpie:
                _string(magpie[key], "magpie." + key)
        if "keep_days" in magpie:
            _integer(magpie["keep_days"], "magpie.keep_days", 1, 365)
        if "max_kib" in magpie:
            _integer(magpie["max_kib"], "magpie.max_kib", 4, 1024)
    return config
