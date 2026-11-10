"""Resolve common Markdown references without importing images or inventing paths.

Supports inline links, Obsidian wikilinks and HTTP(S) autolinks outside fenced,
indented and inline code. Reference-style links and raw HTML are displayed as
text. This is a conservative reference adapter, not a full Markdown parser.
"""

from __future__ import annotations

import html
import posixpath
import re
import unicodedata
from collections import defaultdict
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit

URL_SAFE = ":/?#[]@!$&'*+,;=%~_-"


def _label(value: str) -> str:
    value = html.escape(value.replace("\n", " "), quote=False)
    return re.sub(r"([\\`*_[\]{}|])", r"\\\1", value)


def _literal(value: str) -> str:
    value = value.replace("\r", " ").replace("\n", " ")
    fence = "`" * (max((len(run) for run in re.findall(r"`+", value)), default=0) + 1)
    padding = " " if value.startswith("`") or value.endswith("`") else ""
    return fence + padding + value + padding + fence


def _path(value: str) -> str | None:
    value = unicodedata.normalize("NFC", value.replace("\\", "/"))
    normalized = posixpath.normpath(value)
    if normalized.startswith(("/", "../")) or normalized == "..":
        return None
    return normalized


def _pairs(text: str, opening: str, closing: str) -> dict[int, int]:
    """Index balanced delimiters once, including when a long suffix is malformed."""
    result, stack, index = {}, [], 0
    last_angle = text.rfind(">")
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if opening == "(" and text[index] == "<" and index < last_angle:
            end = text.find(">", index + 1)
            if end != -1:
                index = end + 1
                continue
        if text[index] == opening:
            stack.append(index)
        elif text[index] == closing and stack:
            result[stack.pop()] = index
        index += 1
    return result


QUOTE = re.compile(r" {0,3}> ?")
LIST = re.compile(r"( {0,3})([-+*]|[0-9]{1,9}[.)])( +|(?=\r?$))")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")


def _existing_containers(line: str, containers: list[tuple]) -> tuple[str, list[tuple]]:
    """Remove established quote/list prefixes for block classification only."""
    matched = []
    for kind, width in containers:
        if kind == "quote":
            marker = QUOTE.match(line)
            if not marker:
                break
            line = line[marker.end():]
        elif line.strip():
            if len(line) - len(line.lstrip(" ")) < width:
                break
            line = line[width:]
        matched.append((kind, width))
    return line, matched


def _block_context(line: str, containers: list[tuple], paragraph: bool) -> tuple[str, list[tuple], bool]:
    content, matched = _existing_containers(line, containers)
    if len(matched) != len(containers) and paragraph and content.strip() and not (
            QUOTE.match(content) or LIST.match(content) or FENCE.match(content) or re.match(r" {0,3}#{1,6}(?: |$)", content)):
        # Lazy continuation belongs to the current paragraph, not a new code block.
        return content, containers, False
    new_block = len(matched) != len(containers)
    while True:
        marker = QUOTE.match(content)
        if marker:
            matched.append(("quote", 0))
            content = content[marker.end():]
        else:
            marker = LIST.match(content.rstrip("\r\n"))
            if not marker:
                break
            spaces = marker[3]
            # More than four spaces after a marker can introduce list-item code.
            used = len(spaces) if 1 <= len(spaces) <= 4 else 1
            matched.append(("list", len(marker[1]) + len(marker[2]) + used))
            content = spaces[used:] + content[marker.end():]
        new_block = True
    return content, matched, new_block


def _destination(value: str) -> str:
    value = value.strip()
    angle = re.fullmatch(r'<([^<>]*)>(?:\s+(?:"[^"]*"|\x27[^\x27]*\x27))?', value)
    if angle:
        return angle[1]
    titled = re.fullmatch(r'(.+?)\s+(?:"[^"]*"|\x27[^\x27]*\x27)', value)
    return titled[1] if titled else value


class ReferenceLinks:
    def __init__(self, rows: list[dict]):
        self.origins = defaultdict(list)
        for row in rows:
            document = row["document"]
            if PurePosixPath(document["origin"]).suffix.casefold() == ".md":
                origin = _path(document["origin"])
                if origin is not None:
                    self.origins[(document["source"], origin)].append(row)

    def _unique(self, source: str, origins: list[str]) -> str | None:
        rows = [row for origin in set(origins) for row in self.origins.get((source, origin), [])]
        available = {row["document"]["id"] for row in rows if row["available"]}
        identifiers = available or {row["document"]["id"] for row in rows}
        return next(iter(identifiers)) if len(identifiers) == 1 else None

    def _render(self, title: str, target: str, document: dict, wiki: bool = False, image: bool = False) -> str:
        label = _label(title or target)
        if image:
            return f"图片引用：{label}（原目标：{_literal(target)}；图片未导入）"
        decoded = html.unescape(re.sub(r"\\([()\[\]<> ])", r"\1", target)).strip()
        try:
            parsed = urlsplit(decoded)
            if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc:
                return f"[{label}]({quote(decoded, safe=URL_SAFE)})"
            local = urlsplit(unquote(decoded))
        except ValueError:
            local = None
        identifier = None
        if local and not local.scheme and not local.netloc and not local.query:
            path = local.path.replace("\\", "/")
            origin = _path(document["origin"])
            if origin is not None and not path.startswith("/"):
                if not path:
                    candidates = [origin]
                elif wiki and "/" not in path:
                    name = path if PurePosixPath(path).suffix else path + ".md"
                    candidates = [candidate for source, candidate in self.origins if source == document["source"]
                                  and PurePosixPath(candidate).name == name]
                else:
                    path = path + ".md" if wiki and not PurePosixPath(path).suffix else path
                    candidates = [_path(posixpath.join(posixpath.dirname(origin), path))]
                    if wiki:
                        candidates.append(_path(path))
                    candidates = [candidate for candidate in candidates if candidate is not None]
                identifier = self._unique(document["source"], candidates)
        if identifier:
            suffix = f"（原文位置：{_literal('#' + local.fragment)}）" if local.fragment else ""
            return f"[{label}](../Sources/{quote(identifier, safe='')}.md)" + suffix
        return f"{label}（原引用：{_literal(target)}）"

    def _inline(self, text: str, document: dict) -> str:
        output, index = [], 0
        brackets, parentheses = _pairs(text, "[", "]"), _pairs(text, "(", ")")
        last_wiki, last_angle = text.rfind("]]"), text.rfind(">")
        while index < len(text):
            if text[index] == "\\" and index + 1 < len(text):
                output.append(text[index:index + 2])
                index += 2
                continue
            if text[index] == "`":
                ticks = re.match(r"`+", text[index:])[0]
                end = re.search(r"(?<!`)" + re.escape(ticks) + r"(?!`)", text[index + len(ticks):])
                if end:
                    stop = index + len(ticks) + end.end()
                    output.append(text[index:stop])
                    index = stop
                    continue
                output.append(ticks)
                index += len(ticks)
                continue
            definition = re.match(r" {0,3}\[([^]\n]+)\]:[^\n]*", text[index:]) if index == 0 or text[index - 1] == "\n" else None
            if definition:
                output.append("原引用定义：" + _literal(definition[0].lstrip()))
                index += definition.end()
                continue
            image = text.startswith("![", index)
            start = index + int(image)
            if text.startswith("[[", start) and start < last_wiki:
                end = text.find("]]", start + 2)
                if end != -1:
                    target, separator, title = text[start + 2:end].partition("|")
                    output.append(self._render(title if separator else target, target, document, wiki=True, image=image))
                    index = end + 2
                    continue
            if text.startswith("[", start):
                end = brackets.get(start)
                if end is not None and text.startswith("(", end + 1):
                    stop = parentheses.get(end + 1)
                    if stop is not None:
                        output.append(self._render(text[start + 1:end], _destination(text[end + 2:stop]), document, image=image))
                        index = stop + 1
                        continue
                if end is not None and text.startswith("[", end + 1):
                    stop = text.find("]", end + 2)
                    if stop != -1:
                        title = text[start + 1:end]
                        reference = text[end + 2:stop] or title
                        output.append(f"{_label(title)}（原引用标签：{_literal(reference)}）")
                        index = stop + 1
                        continue
            if text[index] == "<" and index < last_angle:
                end = text.find(">", index + 1)
                if end != -1:
                    target = text[index + 1:end]
                    if re.match(r"https?://", target, re.I):
                        output.append(self._render(target, target, document))
                    else:
                        output.append(_literal(text[index:end + 1]))
                    index = end + 1
                    continue
            output.append(text[index])
            index += 1
        return "".join(output)

    def rewrite(self, text: str, document: dict) -> str:
        output, normal = [], []
        fence, containers, paragraph = "", [], False

        def flush() -> None:
            output.append(self._inline("".join(normal), document))
            normal.clear()

        for line in text.splitlines(keepends=True):
            if fence:
                content, matched = _existing_containers(line.expandtabs(4), containers)
                if len(matched) == len(containers):
                    output.append(line)
                    if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*\r?\n?", content):
                        fence = ""
                    continue
                # A dedent/ended quote closes its nested fenced block.
                fence, containers, paragraph = "", matched, False
            content, context, new_block = _block_context(line.expandtabs(4), containers, paragraph)
            if context != containers:
                flush()
            containers = context
            if new_block:
                paragraph = False
            marker = FENCE.match(content)
            if marker and marker[1][0] == "`" and "`" in content[marker.end():]:
                marker = None
            if marker:
                flush()
                fence = marker[1]
                output.append(line)
                paragraph = False
            elif content.startswith("    ") and not paragraph:
                flush()
                output.append(line)
            elif not content.strip():
                flush()
                output.append(line)
                paragraph = False
            else:
                normal.append(line)
                paragraph = not bool(re.match(r" {0,3}#{1,6}(?: |$)", content))
        flush()
        return "".join(output)

    def summary(self, row: dict) -> dict:
        result = dict(row["summary"])
        result["summary"] = self.rewrite(result["summary"], row["document"])
        for key in ("key_points", "decisions", "questions"):
            result[key] = [self.rewrite(value, row["document"]) for value in result[key]]
        return result
