"""Invented nested notes and assets; no real workspace content is read."""

import copy
import re
import time
import unittest
from pathlib import PurePosixPath
from urllib.parse import unquote
from unittest.mock import patch

from knowledge.common import slug
from knowledge.catalog import Catalog
from knowledge.links import ReferenceLinks
from knowledge.render import projections
from knowledge.service import sync
from test_knowledge import WorkspaceFixture


def source(identifier, origin, text="普通虚构摘要", *, alias="fictional-notes", available=True, day="2026-01-10"):
    return {"document": {"id": identifier, "source": alias, "origin": origin, "kind": "markdown", "day": day,
                         "text": "# 原始虚构资料\n\n" + text},
            "summary": {"title": "虚构资料 " + identifier, "summary": text, "topics": ["虚构主题"],
                        "key_points": [text], "decisions": [text], "questions": [text], "method": "extract"},
            "available": available}


class ReferenceCase(unittest.TestCase):
    def setUp(self):
        self.origin = source("original", "nested/当前笔记.md")
        self.target = source("target", "参考资料/目标 空格.md")
        self.rows = [self.origin, self.target]

    def rewrite(self, value, rows=None):
        return ReferenceLinks(rows or self.rows).rewrite(value, self.origin["document"])

    def test_relative_unicode_and_encoded_spaces_resolve_to_collected_card(self):
        for value in ("[参考](../参考资料/目标%20空格.md)", "[参考](<../参考资料/目标 空格.md>)",
                      '[参考](<../参考资料/目标 空格.md> "原文标题")'):
            self.assertEqual(self.rewrite(value), "[参考](../Sources/target.md)")

    def test_anchors_are_explained_without_inventing_summary_anchors(self):
        result = self.rewrite("[参考](../参考资料/目标%20空格.md#原文小节)")
        self.assertIn("[参考](../Sources/target.md)", result)
        self.assertIn("原文位置：`#原文小节`", result)
        self.assertNotIn("target.md#", result)
        self.assertEqual(self.rewrite("[本节](#原文小节)"), "[本节](../Sources/original.md)（原文位置：`#原文小节`）")

    def test_wikilinks_resolve_unique_basename_and_explicit_relative_path(self):
        for value in ("[[目标 空格|参考]]", "[[参考资料/目标 空格|参考]]", "[[../参考资料/目标 空格|参考]]"):
            self.assertEqual(self.rewrite(value), "[参考](../Sources/target.md)")
        result = self.rewrite("[[目标 空格#标题|参考]]")
        self.assertIn("[参考](../Sources/target.md)", result)
        self.assertIn("原文位置", result)

    def test_ambiguous_wikilinks_and_cross_source_targets_are_not_guessed(self):
        duplicate = source("other", "其他目录/目标 空格.md")
        result = self.rewrite("[[目标 空格|参考]]", self.rows + [duplicate])
        self.assertNotIn("](../Sources/", result)
        self.assertIn("原引用", result)
        separate = source("separate", "参考资料/目标 空格.md", alias="different-source")
        result = self.rewrite("[参考](../参考资料/目标%20空格.md)", [self.origin, separate])
        self.assertNotIn("](../Sources/", result)

    def test_available_version_wins_but_ambiguous_available_versions_do_not(self):
        previous = source("previous", self.target["document"]["origin"], available=False, day="2026-01-09")
        value = "[参考](../参考资料/目标%20空格.md)"
        self.assertIn("../Sources/target.md", self.rewrite(value, self.rows + [previous]))
        previous["available"] = True
        self.assertNotIn("](../Sources/", self.rewrite(value, self.rows + [previous]))

    def test_known_unavailable_note_can_still_link_to_its_retained_card(self):
        self.target["available"] = False
        self.assertIn("../Sources/target.md", self.rewrite("[[目标 空格]]"))

    def test_unknown_assets_and_images_remain_nonactive_references(self):
        for value in ("[数据](../assets/data.csv)", "[失效](missing.md)", "[[missing]]"):
            result = self.rewrite(value)
            self.assertIn("原引用", result)
            self.assertNotRegex(result, r"\]\([^)]+\)")
        for value in ("![原图](../assets/image.png)", "![[image.png|说明]]", "![远图](https://example.org/picture.png)"):
            result = self.rewrite(value)
            self.assertIn("图片未导入", result)
            self.assertNotIn("![", result)
            self.assertNotRegex(result, r"\]\([^)]+\)")

    def test_external_web_links_remain_clickable(self):
        value = "[文档](https://example.org/guide?q=one#section) [站点](http://example.org/)"
        self.assertEqual(self.rewrite(value), value)
        self.assertEqual(self.rewrite("<https://example.org/>"), "[https://example.org/](https://example.org/)")

    def test_unsafe_schemes_and_absolute_machine_paths_are_nonactive(self):
        for target in ("javascript:alert(1)", "data:text/html,boom", "file:///D:/private/note.md",
                       "C:\\private\\note.md", "/home/person/note.md", "//server/share/note.md",
                       "%6Aavascript%3Aalert(1)"):
            result = self.rewrite("[引用](" + target + ")")
            self.assertIn("原引用", result, target)
            self.assertNotRegex(result, r"\]\([^)]+\)", target)
        self.assertEqual(self.rewrite("<file:///D:/private/note.md>"), "`<file:///D:/private/note.md>`")

    def test_code_is_preserved_and_unclosed_ticks_do_not_hide_links(self):
        code = "```md\n[不要改](missing.md)\n```\n~~~\n[[不要改]]\n~~~\n    [缩进代码](missing.md)\n`[行内](missing.md)` and ``[[行内]]``"
        self.assertEqual(self.rewrite(code), code)
        value = "prefix ```` unclosed [链接](missing.md) ``"
        self.assertIn("原引用", self.rewrite(value))
        self.assertEqual(self.rewrite(r"\[已转义](missing.md)"), r"\[已转义](missing.md)")

    def test_reference_style_and_html_do_not_leave_active_local_links(self):
        value = '[文本][ref]\n[ref]: missing.md\n<a href="file:///private.md">本机</a>'
        result = self.rewrite(value)
        self.assertIn("原引用标签", result)
        self.assertIn("原引用定义", result)
        self.assertNotIn('\n[ref]:', result)
        self.assertIn('`<a href="file:///private.md">`', result)

    def test_list_quote_and_paragraph_continuations_rewrite_active_links(self):
        target = "[参考](../参考资料/目标%20空格.md)"
        for value in (f"- item\n    {target}\n", f"1. item\n\t{target}\n",
                      f"- outer\n    - inner\n        {target}\n",
                      f"> {target}\n", f"> - item\n>     {target}\n",
                      f"- item\n    > {target}\n", f"paragraph\n    {target}\n"):
            self.assertIn("[参考](../Sources/target.md)", self.rewrite(value), value)
        for prefix in ("- item\n    ", "> - item\n>     ", "- outer\n    - inner\n        "):
            result = self.rewrite(prefix + "[引用](javascript:alert(1))\n")
            self.assertIn("原引用", result)
            self.assertNotIn("](javascript:", result)

    def test_true_indented_code_and_container_fences_are_unchanged(self):
        for value in ("    [code](missing.md)\n", "paragraph\n\n    [code](missing.md)\n",
                      "- item\n\n      [code](missing.md)\n",
                      "- outer\n    - inner\n\n          [code](missing.md)\n",
                      ">     [code](missing.md)\n",
                      "> ```md\n> [code](missing.md)\n> ````\n",
                      "- ```md\n  [code](missing.md)\n  ```\n",
                      "- > ```md\n  > [code](missing.md)\n  > ```\n"):
            self.assertEqual(self.rewrite(value), value)

    def test_ended_quote_or_list_fence_does_not_hide_outside_links(self):
        reference = "[参考](../参考资料/目标%20空格.md)"
        for code in ("> ```md\n> [code](missing.md)\n", "- ```md\n  [code](missing.md)\n"):
            result = self.rewrite(code + reference + "\n")
            self.assertTrue(result.startswith(code))
            self.assertIn("[参考](../Sources/target.md)", result)

    def test_long_unclosed_brackets_have_bounded_processing(self):
        value = "[" * 12000
        started = time.perf_counter()
        self.assertEqual(self.rewrite(value), value)
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_balanced_parentheses_and_nfc_names_are_supported(self):
        target = source("version", "参考资料/目标 (v2).md")
        self.assertEqual(self.rewrite("[新版](<../参考资料/目标 (v2).md>)", self.rows + [target]), "[新版](../Sources/version.md)")
        decomposed = source("unicode", "参考资料/cafe\u0301.md")
        self.assertEqual(self.rewrite("[名字](../参考资料/caf\u00e9.md)", self.rows + [decomposed]), "[名字](../Sources/unicode.md)")

    def test_projections_rewrite_all_fields_without_mutating_inputs(self):
        reference = "[目标](../参考资料/目标%20空格.md#来源标题) ![图](image.png)"
        row = source("original", "nested/当前笔记.md", reference)
        rows = [row, self.target]
        original = copy.deepcopy(rows)
        config = {"sources": [], "engine": {"name": "extract"}, "timezone": "UTC", "include_raw": True}
        with patch("knowledge.reflection.current_day", return_value="2026-01-11"), patch("knowledge.personal_render.current_day", return_value="2026-01-11"):
            first = projections(rows, config)
            second = projections(rows, config)
        self.assertEqual(first, second)
        self.assertEqual(rows, original)
        self.assertEqual(first["Archive/original.md"], "# 规范化来源正文\n\n" + row["document"]["text"] + "\n")
        expected = "[目标](../Sources/target.md)"
        self.assertEqual(first["Sources/original.md"].count(expected), 4)
        self.assertEqual(first["Daily/2026-01-10.md"].count(expected), 3)
        self.assertEqual(first[f"Wiki/{slug('虚构主题')}.md"].count(expected), 3)
        for name in ("Sources/original.md", "Daily/2026-01-10.md", f"Wiki/{slug('虚构主题')}.md"):
            self.assertNotIn("![", first[name])
            for path in re.findall(r"\]\((\.\./Sources/[^)]+)\)", first[name]):
                destination = posix_normalize(PurePosixPath(name).parent / unquote(path))
                self.assertIn(destination, first)


def posix_normalize(path):
    parts = []
    for part in path.parts:
        if part == "..":
            parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


class LinkWorkspaceCase(WorkspaceFixture, unittest.TestCase):
    def test_real_synthetic_files_generate_only_existing_local_link_targets(self):
        nested = self.source / "nested"
        target = self.source / "参考资料"
        nested.mkdir()
        target.mkdir()
        (nested / "当前笔记.md").write_text(
            "---\ndate: 2026-01-10\n---\n# 虚构嵌套笔记\n\n"
            "参考 [目标](<../参考资料/目标 空格.md#原文节>) 和 [[目标 空格|知识引用]]。\n"
            "![示意图](../images/not-imported.png) [数据](../data/not-imported.csv)\n", encoding="utf-8")
        (target / "目标 空格.md").write_text("---\ndate: 2026-01-10\n---\n# 虚构目标\n\n只包含虚构内容。", encoding="utf-8")
        self.configure()
        sync(self.root)
        catalog = Catalog(self.root)
        try:
            target_id = next(row["document"]["id"] for row in catalog.rows() if row["document"]["origin"] == "参考资料/目标 空格.md")
        finally:
            catalog.close()
        links_checked = 0
        for page in self.root.rglob("*.md"):
            if ".knowledge" in page.parts:
                continue
            text = page.read_text(encoding="utf-8")
            self.assertNotIn("![示意图]", text)
            for destination in re.findall(r"\]\(([^)]+)\)", text):
                if destination.startswith(("https://", "http://")):
                    continue
                filename, _, fragment = unquote(destination).partition("#")
                result = (page.parent / filename).resolve()
                self.assertTrue(result.is_relative_to(self.root.resolve()), (page.name, destination))
                self.assertTrue(result.is_file(), (page.name, destination))
                if fragment:
                    self.assertIn(f'id="{fragment}"', result.read_text(encoding="utf-8"))
                links_checked += 1
        self.assertGreater(links_checked, 20)
        daily = (self.root / "Daily/2026-01-10.md").read_text(encoding="utf-8")
        self.assertIn(f"../Sources/{target_id}.md)", daily)
        self.assertIn("原文位置", daily)


if __name__ == "__main__":
    unittest.main()
