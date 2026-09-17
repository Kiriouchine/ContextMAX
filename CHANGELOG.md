# Changelog

All notable changes to ContextMAX are recorded here. The format follows
Keep a Changelog, and the project follows Semantic Versioning.

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
