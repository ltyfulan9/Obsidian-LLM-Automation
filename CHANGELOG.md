# Changelog

## 0.3.0

- Add bounded gzip conversation-summary bundles carried by Magpie's registered Library integration, with explicit private-target checks.
- Add OS advisory locks, recoverable render journals, successful-chunk caches, bounded timeout retries and process-tree cleanup.

- Add a generated `Sync.md` page and `knowledge plan` preview of exact source/publication scope.
- Add fixed first-import date cutoffs through `source --recent-days 7`.
- Add repeating 30-minute schedules for Windows and macOS.
- Document Magpie configuration backup versus AI conversation summaries and private knowledge publication.
- Validate repeated synthetic conversation updates; keep all real personal data out of the public experiment.
- Fix the Windows task XML declaration for PowerShell's in-memory registration API.

## 0.2.0

- Shared Python 3.10+ core for Windows and macOS, replacing the primary Windows-only workflow.
- Explicit-source import for Markdown, Codex/Claude Code JSONL, generic JSON and Claude conversation exports.
- Timezone-aware daily notes, topic Wiki, timeline, Mermaid maps and Obsidian Canvas.
- Local extraction and optional structured Codex/Claude summaries with long-conversation chunking.
- Transactional catalog, content-hash deduplication, handwritten-note boundaries and generated-edit detection.
- Private-only Git publication, native scheduler definitions and a Linux/Windows/macOS CI matrix.
- The previous Windows archive script remains a legacy workflow, separate from v0.2 workspaces.
