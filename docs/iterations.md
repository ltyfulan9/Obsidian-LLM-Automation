# Three product iterations

Baseline: v0.4.0, commit `44faf5e`. The product, engineering and design reviews were performed independently before implementation. Private workspaces, personal preferences and real conversation content are excluded from this public work.

## Round 1 — A verifiable first run

Problem: users must prepare sources before they can try the product; malformed configuration can raise a traceback; there is no safe offline diagnostic entry point.

Delivered: an invented offline `demo`, a read-only `doctor`, shared configuration validation, and a daily reading entrance with clear empty states and summary provenance. Generated-output feedback loops, native subagent sessions and assistant analysis-channel ingestion are blocked.

Acceptance: a fresh directory completed a real Python CLI demo, diagnosis and search journey; repeated demo refused overwrite and doctor preserved every file hash. A missing source was identified by alias with exit code 1. Product acceptance tests isolate provider and network calls. Unicode/space directory names were independently exercised.

Cross-role corrections: design review found that diagnostic text hid source identifiers and overstated readiness; both were corrected. Engineering reproduced an old-workspace manual-entry path that bypassed the new Notes guide; check-in/task refresh now upgrades only missing guides and preserves handwritten contents. Product review confirmed that local diagnostics do not imply tested inference, publication or installed scheduling. Search explanations, original relative links and complete recovery remain open for subsequent rounds.

Local validation passed 87 tests. Initial cross-platform CI exposed two tests comparing lexical temporary paths against canonical paths (Windows short names and macOS aliases); those tests now compare canonical paths, matching the filesystem invariant rather than a platform-specific spelling.

## Round 2 — Useful everyday knowledge

Planned acceptance: search explains matches and allows date filtering; source-relative links cannot become dangling links in generated views; confirmed task results appear in review evidence; the daily task flow stays separate from AI suggestions.

## Round 3 — Recovery and operational trust

Planned acceptance: verified state backup/restore into a fresh workspace preserves personal records and incremental state; damaged/unsafe packages leave no partial workspace; recent failures and last success are shown separately; Windows/macOS diagnostics and synthetic end-to-end CI pass.

Each round must contain shipped behavior, cross-role review, corrections and actual CLI verification. Three document edits do not count as three iterations.
