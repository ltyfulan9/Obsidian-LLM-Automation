# Three product iterations

Baseline: v0.4.0, commit `44faf5e`. The product, engineering and design reviews were performed independently before implementation. Private workspaces, personal preferences and real conversation content are excluded from this public work.

## Round 1 — A verifiable first run

Problem: users must prepare sources before they can try the product; malformed configuration can raise a traceback; there is no safe offline diagnostic entry point.

Delivered: an invented offline `demo`, a read-only `doctor`, shared configuration validation, and a daily reading entrance with clear empty states and summary provenance. Generated-output feedback loops, native subagent sessions and assistant analysis-channel ingestion are blocked.

Acceptance: a fresh directory completed a real Python CLI demo, diagnosis and search journey; repeated demo refused overwrite and doctor preserved every file hash. A missing source was identified by alias with exit code 1. Product acceptance tests isolate provider and network calls. Unicode/space directory names were independently exercised.

Cross-role corrections: design review found that diagnostic text hid source identifiers and overstated readiness; both were corrected. Engineering reproduced an old-workspace manual-entry path that bypassed the new Notes guide; check-in/task refresh now upgrades only missing guides and preserves handwritten contents. Product review confirmed that local diagnostics do not imply tested inference, publication or installed scheduling. Search explanations, original relative links and complete recovery remain open for subsequent rounds.

Local validation passed 87 tests. Initial cross-platform CI exposed two tests comparing lexical temporary paths against canonical paths (Windows short names and macOS aliases); those tests now compare canonical paths, matching the filesystem invariant rather than a platform-specific spelling.

Corrected round-one CI passed all six Linux/Windows/macOS × Python 3.10/3.12 jobs at commit `50f2953` ([run](https://github.com/ltyfulan9/Obsidian-LLM-Automation/actions/runs/42846446366)).

## Round 2 — Useful everyday knowledge

Delivered: content-field relevance, snippets, source/method/availability explanations, activity-date/type filtering, open/overdue task lists and completed-outcome review evidence. A shared reference converter resolves known original notes to source cards and preserves unknown targets as nonactive references.

Cross-role corrections: product acceptance found that `task add --format text` silently ignored a list-only option; it now refuses before writing. Engineering verified historical outcome replay and list intersections. Root review found that four-space list continuations were incorrectly treated as code and that unmatched brackets could cause repeated scanning. Design added container-aware handling and a one-pass delimiter index; 12k malformed brackets processed in about 13ms in the synthetic check. Genuine code and original archive text remain unchanged.

Acceptance includes real CLI search → task completion → review, historical filters that exclude later outcomes, and on-disk nested Unicode/space note links with actual target/anchor checks. Backup/restore and durable failed-attempt visibility remain the third-round gate.

Local validation passed 126 tests. A real CLI journey imported four invented documents, checked 62 active local links and reached a recorded completion outcome through review evidence. The static invented example was regenerated from the same core.

Round-two cross-platform CI passed at `3d46f73` ([run](https://github.com/ltyfulan9/Obsidian-LLM-Automation/actions/runs/42848987121)).

## Round 3 — Recovery and operational trust

Delivered: verified private state packages, new-directory restore/dry-run, strict catalog structural checks, staged sync attempts, confirmed-save indicators and correlated schedule logs. Recovery preserves pending render intent and edited pages that were not yet in the ownership registry.

Cross-role corrections: product review identified missing catalogs being silently recreated; only initialization can now create them. Engineering tightened column/order/type/primary-key checks before summaries or writes. Design found lock-blocked logging reusing an old success; per-invocation UUIDs now emit a separate blocked-start event without altering the active owner's state or lock. State metadata shape and recovery hints are validated instead of trusting arbitrary saved text.

Acceptance covers a real CLI backup → dry-run → fresh restore → build/search/review journey, unsafe/tampered package refusal, pending-generation recovery, saved-stage failures, lock interruption and no raw/provider-error content in operational metadata.

Final local validation passed **171 tests**. The built v0.5.0 wheel was installed into a separate environment and exercised outside the source checkout. A native Windows scheduled job executed with exit code 0, imported no real data, reported zero updates/two unchanged records, and produced a log matching its new invocation UUID. The temporary OS task was removed. No new real model inference or user-Mac launchd registration is claimed. Final cross-platform results are linked from [validation](validation.md).

Each round must contain shipped behavior, cross-role review, corrections and actual CLI verification. Three document edits do not count as three iterations.
