# Architecture

## Domain and boundaries

The public **tool repository** contains code and invented fixtures. A separate **knowledge workspace** contains the user's material and can be a private GitHub repository. An Obsidian vault or CLI session directory is a read-only **source**.

A **document** is one Markdown file or one conversation/day pair. Its stable ID derives from the source alias, relative filename, exported conversation identity and local calendar date. Moving a file or changing its source alias creates a new document; old records remain as history.

A **source card** is a dated summary with source references, topics, key points, explicit decisions and unresolved questions. Daily pages, topic pages and maps are projections of the same catalog, so the two navigation dimensions agree.

A **check-in** is a dated self-report of completed work, blockers and lessons. A **commitment** is explicitly confirmed by the user, with an optional deadline, expected result and source-card reference. Its append-only status events record deferrals, actual outcomes, cancellation and reopening. Imported plans and AI questions never create commitments automatically. A **review** applies transparent local rules to those observations and events, retaining evidence and uncertainty rather than rating a person.

```mermaid
flowchart LR
    A[Configured read-only sources] --> B[Adapters and privacy filter]
    B --> C[Normalized documents]
    C --> D[Validated summarizer]
    D --> E[SQLite catalog]
    E --> F[Daily / Wiki / Timeline]
    E --> G[Mermaid / Obsidian Canvas]
    F --> H[Optional private-only Git publication]
    G --> H
```

## Modules

| Module | Owns | Does not own |
| --- | --- | --- |
| `ingest.py` | File filtering, native adapters, timezone date split, source identity | Model calls, output files |
| `summarize.py` | Extraction, CLI invocation, chunking, strict result validation | Workspace paths and Git |
| `catalog.py` | Transactional content/engine hashes, summaries, availability | Rendering |
| `reflection.py` | User-confirmed check-ins, commitment transitions, historical state and review rules | Model calls or personality judgments |
| `personal_render.py` | Daily self-reports, task history and evidence-linked weekly projections | Source ingestion or task inference |
| `render.py` | Markdown, deterministic topic paths, maps, edit detection | Source reads and provider configuration |
| `publish.py` | Exact generated-file staging, secret checks, private GitHub guard | Collection or model selection |
| `service.py` | Pipeline order, locking, config validation, run result | Native OS registration |
| `config.py` | Pure, field-specific configuration validation shared by readers and writers | Filesystem inspection |
| `doctor.py` | Read-only local readiness checks; explicit optional private-target check | Repairs, source-body reads or model calls |
| `demo.py` | An offline first-run journey made entirely of invented records | Real personal source discovery |
| `query.py` | Keyword matching, field relevance, bounded snippets and historical activity filters | Models, vectors or metadata-as-content search |
| `links.py` | Conservative original-reference resolution shared by every summary projection | Original archive rewriting or guessing ambiguous references |
| `backup.py` | Verified operational snapshots and fresh-directory restoration | External source attachments, Git/CLI authentication or automatic publication |
| `runstate.py` | Atomic latest-attempt/last-success metadata, lock observation and correlated operational logs | Source content, provider stderr or OS task registration claims |
| `schedule.py` | launchd plist / Task Scheduler XML | Installing or enabling jobs |

## Failure semantics

Collection reads explicit roots and applies include/exclude globs. Sources cannot contain the output workspace. Individual missing records are retained and marked unavailable. A missing source root fails the run instead of declaring its entire contents deleted.

Generated directories and generated root pages cannot be registered as sources. The same managed-path policy is used by ingestion and diagnostics. Handwritten `Notes/` remains a valid explicit source. Codex sessions marked as subagents in session metadata, as well as assistant analysis-channel messages, are excluded independently of filesystem layout.

Configuration validation is a pure operation: invalid value types produce field-specific errors before configuration replacement. `doctor` inspects metadata and generated-file ownership without opening source bodies, calling providers or modifying state. Database journals defer integrity inspection; a readable CLI executable does not establish authentication or successful inference. Publishing readiness is checked online only with an explicit option.

Initialization and compatible upgrades create a `Notes/README.md` guide only when absent, using exclusive creation. Existing handwritten content is never replaced. The generated home page links to this stable handwritten entrance and distinguishes confirmed commitments from imported suggestions.

Content and engine configuration hashes decide whether a summary needs updating. Model failures roll back the current catalog transaction. Rendering follows a successful transaction and can be retried with `knowledge build` without repeating model calls.

Every generated file is registered with a content hash. Before generation, edits to existing generated pages stop the build. Move intended handwritten edits to `Notes/`, restore the generated page, then retry. A durable render journal records old hashes and intended content before pages change. The next build resumes an interrupted generation, accepting only old or intended hashes; edits made after interruption stop recovery. This is recoverable multi-file generation, not a filesystem-wide transaction.

The workspace uses an OS advisory lock: a process exit releases it even if the lock file remains. Successful model chunks are cached under ignored local state, so a later model or catalog failure does not discard paid successful calls. Timeouts clean up the spawned process group and retry a bounded number of times.

Local collection and Git publication are separate. A publication failure does not roll back successfully collected knowledge. `knowledge publish` retries Git without reprocessing sources. Conflicts need human resolution; the tool never force pushes or silently rebases.

Each sync records its phase and confirmed saves. One atomic `run-state.json` envelope owns the latest attempt and last complete success; `last-run.json` remains a compatibility mirror. Failure metadata uses fixed codes and recovery hints, never source bodies or provider stderr. False save flags mean unconfirmed, not proof that a remote operation did not occur. A recorded running attempt with a released lock is reported interrupted without modifying state. Manual build/publish recovery does not pretend to be a new complete sync.

Generated schedules request `sync --log`. CLI invocation IDs prevent a lock-blocked command from logging another run's success. Logs distinguish blocked startup from failed pipeline stages. Markdown pages point to live status commands rather than embedding a stale running snapshot.

State packages contain a consistent SQLite snapshot, configuration, ownership registry, generated pages, Notes bytes/timestamps and recovery metadata, including pending render intent. Versioned manifests verify size and SHA-256. Portable-path checks, link rejection, uniqueness and extraction budgets precede fresh-directory presentation. Restore does not collect, infer, build or publish. Packages are private but unencrypted; external attachments, unmanaged legacy folders and Git/authentication need separate backup.

Normal catalog open requires an existing database and validates known columns, order, types and primary keys before compatible upgrades. Only initialization explicitly creates a database; a missing catalog cannot become an apparently empty successful search.

Personal tables are added in place when opening an older catalog. Check-ins merge with exact deduplication, unless explicitly replaced; commitment events preserve date order per task. Saved personal facts remain committed if rendering fails; the error distinguishes this state and `knowledge build` regenerates pages without another provider call. Weekly projections replay only events up to the week-end cutoff, while the current week stops at today. They can change after intentional historical corrections; they are not immutable audit snapshots.

With `--push`, the target is verified private before collection and again immediately before transmission. Provider stderr and raw result bodies are not printed, since they can echo private prompts.

## Meaning and limits

Extraction is labeled as an excerpt. AI summaries are labeled for verification and retain source aliases/relative paths. Topic pages aggregate dated evidence and deduplicate decisions/questions; they do not adjudicate contradictory claims or create a verified biography.

Summary references are interpreted in the original document's context before projecting into source, day and topic pages. An unambiguous collected Markdown target links to its source card. Original anchors are retained as explanatory text rather than invented summary anchors. Missing assets, ambiguous references, unsupported link forms, images and unsafe schemes are displayed as nonactive references; fenced/inline code and actual indented code are preserved. This adapter supports common Markdown and Obsidian references, not the entire Markdown grammar. Normalized raw archives remain unchanged.

Search matches AND keywords against explicit content fields, not serialized JSON keys or metadata. Relevance by title, topics, summary, structured records and body precedes recency; ties are stable by file. Results retain origin alias, actual summary method, availability, matched fields and a bounded excerpt. Date filters use document/check-in dates and task activity dates; task outcomes outside a historical window cannot contribute a match.

Completed commitments contribute their expected/actual outcomes and exact completion-event link to review accomplishments. Daily self-reports remain separately labeled and are not manufactured from task completion.

Normalized text is held in ignored local SQLite state. `include_raw` defaults to `false`; enabling it adds normalized text to `Archive/` for optional private publication. This is a text knowledge importer, not a byte-for-byte backup of images, PDFs, plugin state or session metadata. The legacy archive script serves that older use case.

Turning raw archives off removes those generated files from later snapshots and publication, but does not purge earlier private Git history.

Review rules flag overdue open commitments, at least two deferrals of the same task in 28 days, and identical blocker wording on at least three distinct dates in 28 days. They ask the user to check explanations; missing observations are unknown, and causal, personality or medical conclusions are outside the model. The generated Markdown is a readable export; operational personal state remains in ignored SQLite and needs a separate secure local backup for migration.
