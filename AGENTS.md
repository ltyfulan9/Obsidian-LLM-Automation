# Development rules

This public repository contains the knowledge tool, documentation and synthetic examples. Personal knowledge workspaces live outside the checkout.

- Read `docs/architecture.md` when changing ingestion, storage, generation or publication boundaries.
- Keep all note and session sources read-only. Import only configured sources; fixtures and demos must use invented data.
- Keep provider output as validated structured data. Python owns paths, dates, Markdown, Canvas and Git operations.
- Preserve source references and distinguish extraction, AI summaries, plans and verified results.
- Keep `.knowledge/` and real transcripts out of Git. Verify private visibility before any `sync --push` source read and again before publication.
- Keep handwritten `Notes/` intact and stop before overwriting user edits to generated pages.
- Run `python -m unittest discover -s tests -p "test_*.py" -v` after behavior changes. Cross-platform CI is required for the Python core.
- Report whether model calls and native schedulers were actually exercised; mocked tests do not establish live provider or OS behavior.
