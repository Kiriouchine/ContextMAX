# Changelog

All notable changes to ContextMAX are recorded here. The format follows
Keep a Changelog, and the project follows Semantic Versioning.

## [Unreleased]

Phase 3, documents wave, in progress.

### Added
- Document adapters: `pdf-v1` (pypdf; bookmarks as the table of contents, derived headings
  otherwise, page cites such as `thesis.pdf p.33-59 §5`, link annotations, scan detection,
  pypdf warnings recorded as notes), `bibtex-v1`, `notebook-v1`, `rst-v1`, `asciidoc-v1`,
  `org-v1`, `email-v1` (`.eml` and `.mbox`, attachments as references) and `config-v1`
  (JSON, JSON Lines, YAML subset, TOML, XML, INI, dependency manifests; keys as sections,
  path and URL values as references).
- Bibliography entries are reference nodes (`ref:<bib>#<key>`); `\cite{key}` resolves to
  them with high confidence, and an entry's `file` field resolves to the project document.
- Sections and references carry `page` / `end_page` for page-based formats.
- Search ranks names above body text and bare file rows below symbols and sections.
- `CONTEXTMAX_NO_OPTIONAL_READERS=1` makes every version-bound reader unavailable so golden
  and determinism tests never depend on which optional packages a machine has.
- Container formats with the standard library: `ooxml-v1` (Word: heading styles by name,
  lists, tables, hyperlinks, footnotes, comments, TOC field noted, paragraph cites `¶12`;
  PowerPoint: one section per slide with title placeholder or first text line, notes,
  tables, pictures, slide cites `slide 7`), `odf-v1` (.odt/.odp/.odg and flat XML),
  `epub-v1` (spine chapters through the HTML adapter, chapter cites), `rtf-v1` (stylesheet
  headings, bold headings, code pages, Unicode escapes, hyperlink fields, tables),
  `image-v1` (dimensions from PNG/JPEG/GIF/BMP/WebP headers, EXIF text with Pillow; no OCR)
  and `legacy-office-v1` (.doc/.ppt through LibreOffice `soffice --headless` when installed,
  environment-bound with the converter version recorded; catalogued with the reason
  otherwise).
- Zip guards for every package format: password-protected, oversized, extreme-ratio members
  and XML entity declarations are refused with the reason recorded.
- Discovery consults each adapter's `available()` and records `reader-unavailable` with the
  adapter's own reason (for example "install LibreOffice").

### Fixed
- The `max_lines` limit no longer excludes container formats (PDF, Office): three large PDFs
  in the example archive were wrongly skipped as "too many lines".

## [0.2.0] - 2026-09-17

Phase 2, real code analysis: syntax trees wherever a grammar exists, still never touching the
network while indexing.

### Added
- Grammar provisioning: `cmx grammars fetch <names> | --for-project | --all`, `status`, `list`;
  a ledger under `~/.contextmax/grammars` (`CONTEXTMAX_GRAMMAR_DIR`); indexing only loads
  grammars whose bundle is already present. `cmx doctor` reports the grammar state.
- Tier B generic analyzer (`treesitter-tags-v1`): definitions and call references from each
  grammar's bundled tags query with exact spans and nesting; prototypes distinguished from
  definitions; lexical imports, regions and macros merged in; lexical call sites, marked as such,
  when a tags query has no reference patterns.
- Tier A Python plugin (`python-ast-v1`): exact spans, nested definitions, module-level and
  class-body calls, constants, fields, decorators, docstrings, typed parameters, and resolution
  hints that follow imports and `self`/`cls` (evidence `import-resolved`, `self`, `class`).
- Per-file analysis cache (`cache/`) keyed by content hash, adapter and version; a cached
  rebuild is byte-identical to `cmx index --full`.
- A worker process for tier B that survives native crashes: the file is recorded as
  `grammar-crash`, analysed lexically, and the worker restarts on the rest.
- Confidence by tier and evidence on every call edge; per-tier counts in coverage; `CODEMAP.md`
  shows the tier of every symbol.

### Changed
- The tree-sitter bindings are pinned below 0.26: 0.26 crashes with the language pack's
  grammars.
- Golden and determinism tests run with an empty grammar folder so results never depend on what
  a machine has downloaded; CI provisions grammars and runs the tier B tests on three systems.

## [0.1.0] - 2026-09-17

Phase 1, the walking skeleton: a person or an agent can index a project, ask cited questions,
open offline views and install a skill, using only the standard library.

### Added
- Code analysis contract (`code/base.py`) and the tier C lexical analyzer with 30 language
  profiles (`registry/lexical.json`): definitions, calls, imports, regions, documentation,
  parameters, returns; MATLAB scripts as callable nodes; index-or-call gating.
- Project-wide resolution with ambiguity kept as candidate lists, builtins and non-project
  imports labelled external, bare calls gated; `nodes/symbols.jsonl`, `edges/calls.jsonl`,
  `edges/imports.jsonl`, `edges/contains.jsonl`, `CODEMAP.md`.
- Document adapters for Markdown, plain text, HTML and LaTeX; outline tree with stable section
  ids, text cache, references (links, figures, includes, cross-references, citations, path
  mentions) resolved against the project; `nodes/documents.jsonl`, `nodes/sections.jsonl`,
  `nodes/references.jsonl`, `DOCMAP.md`.
- Graded links between sections, symbols, documents and files (`edges/links.jsonl`).
- Deterministic layered and clustered graph layout; `graph/graph.json`.
- SQLite query store with FTS5, rebuilt when the index changes; query API and `cmx q` verbs:
  status, search, find, symbol, callers, callees, impact, file, deps, docs, doc, outline,
  section, refs, related, explain, skipped, source.
- Offline HTML views `viz/index.html`, `viz/code.html`, `viz/docs.html` (single file, no
  external resources, counts equal to `coverage.json`).
- Skill generation following the Agent Skills specification with a host registry (Claude Code,
  Claude Desktop zip, GitHub Copilot, Cursor, Codex, Windsurf, AGENTS.md, CLAUDE.md,
  copilot-instructions, custom); `cmx skill render|install|hosts`; `cmx viz`.
- `INDEX.md` with entry points, most-called symbols and largest documents.
- User guide (`docs/adopting.md`) and machinery reference (`docs/how-it-works.md`).

### Changed
- LaTeX build artifacts are catalogued as generated files; container formats such as PDF and
  OOXML are no longer demoted for containing binary bytes; `init` only touches `.gitignore`
  inside a git repository.

## [0.0.1] - 2026-09-17

Phase 0 foundations: package skeleton, deterministic I/O, configuration schema and validator,
language and format registries with detection, gitignore matcher, discovery with tiers and
recorded skips, stage ledger, coverage, manifest with baseline and artifact identity hashes;
`init`, `index`, `status`, `doctor`; three-OS CI with a cross-platform hash comparison.
