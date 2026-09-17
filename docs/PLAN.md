# ContextMAX — Design and Project Plan

## Status

| Phase | State | Notes |
|---|---|---|
| 0 Foundations | done (2026-09-17) | package skeleton, config schema + validator, registries + detection, gitignore matcher, discovery with tiers, ledger, coverage, manifest with identity hashes, `init`/`index`/`status`/`doctor`, 50 tests, 3-OS CI |
| 1 Walking skeleton | done (2026-09-17, v0.1.0) | [phases/phase-1.md](phases/phase-1.md): lexical analyzer with 30 profiles, Markdown/plain/HTML/LaTeX adapters, structure and text cache, references, graded links, deterministic layout, query store and `cmx q`, three offline pages, skill generation for ten hosts; 108 tests |
| 2 Real code analysis | done (2026-09-17, v0.2.0) | [phases/phase-2.md](phases/phase-2.md): grammar provisioning with a ledger, tier B tags analyzer in a crash-tolerant worker, Python tier A plugin with import and self resolution, per-file cache identical to a full build; tree-sitter pinned below 0.26 |
| 3 Documents wave | next | PDF, Office, OpenDocument, spreadsheets, notebooks, BibTeX, terms and concepts, bibliography parsing |
| 4–9 | planned | see roadmap in section 17 |

## 1. Context

ContextMAX is a downloadable, local, offline tool that a person (or an AI agent on their behalf) runs on any folder or set of files. It indexes, graphs and links everything it finds **deterministically, with no AI in the loop**, and then generates skills and agent instructions so that Claude Code, Claude Desktop, VS Code Copilot, Cursor, Windsurf, Codex and any other AI system know how to search, navigate and cite the result. The purpose is to give a researcher, human or AI, a very fast way into a project's knowledge base with exact pointers back to the original sources.

The author built a predecessor for this idea (Windows-only, profile-driven, engineering-programme oriented). Its strongest ideas are carried forward; its limitations are designed out. The plan was written against an empty repository.

### Decisions already taken with the user

| Topic | Decision |
|---|---|
| Runtime | Python 3.11+, one package, one CLI `contextmax` (alias `cmx`), cross-platform (Windows first-class, macOS, Linux). No PowerShell/cmd orchestration. |
| Code parsing | tree-sitter with language plugins, Python stdlib `ast` for extra Python detail, tiered fallback so **every file** lands in the graph. |
| Languages / formats | **All** languages and **all** document formats, via tiers: dedicated plugin → generic grammar → lexical parser → text/binary fallback. A file missing from the graph because of its language or format is a defect. |
| AI interface | Generated skill files **and** a deterministic query CLI **and** a local MCP server (stdio) exposing the same query library. |
| Index location | Inside the project in `.contextmax/` (gitignored except `config.json`), with an optional external location override. |
| Visualization | Offline single-file HTML views from the first releases; the HTML is the user's sanity check and must mirror the data files exactly. |
| Honesty | Every fact and edge carries provenance and a tier/confidence. The skill tells the agent the graph is a fast way in, may miss things, and must cite the original source it found. |
| License and author | Apache License 2.0. Author and copyright holder: Vsevolod Kiriouchine. No AGPL dependency in the default install; PyMuPDF only as an explicit opt-in extra. |

### Ideas carried forward from the predecessor (kept)

- Engine / per-project config / generated output split. "A keyword in the engine is a bug."
- Determinism doctrine: sorted everything, canonical JSON hashing, ordinal sorting, no RNG, explicit tie-breaks, layout computed in Python and shipped with the data.
- Two identity hashes: baseline (inputs) vs artifact (outputs); machine paths, timestamps and capability inventories excluded from identity.
- Format registry as data with a determinism class per adapter (`intrinsic`, `version-bound`, `environment-bound`, `catalog-only`), adapter id and version stamped on every record.
- "Absence is never silent": a skipped list with reasons, coverage counts, a completeness verdict, a stage ledger saved after every stage.
- Graded edges (never an unlabelled "related"); exact vs topical; "a parameter is a variable name, not a number"; tables kept row-per-line; comments blanked not removed so line numbers stay exact.
- Cloud-placeholder detection, zip-bomb guards, script-injection escaping, no external URLs in generated pages.
- Skill answer contract, trust footer, recipes that name the exact command, host registry where only path and frontmatter vary, marker-block merge for shared files.
- Testing philosophy: two-run hash equality, shuffled-input equality, hash sensitivity both ways, "absence is recorded" tests, synthetic fixtures, locale-hostile names, security regressions, browser smoke.

### Weaknesses of the predecessor to design out

| Weakness | ContextMAX answer |
|---|---|
| Windows-only orchestration, PowerShell recipes | Pure Python; recipes are CLI commands and MCP tools |
| Calls resolved by bare name, no import resolution, ambiguity silently collapsed, module-level code invisible, multiplicity lost | Scope/import-aware plugins, project-wide graph, `candidates` recorded, call sites with counts, module-level calls captured |
| Adding a language touched five places; per-language output files/schemas | One node schema, one edge schema, one plugin contract, one set of output files |
| Entity id `path:line:name` breaks on every edit | Stable ids from path + qualified name (+ signature ordinal); line kept as a separate field |
| Thin document structure (flat headings, no TOC/chapters/bibliography, document-level edges only) | Outline tree, TOC, sections with text ranges, tables/figures/footnotes, terms, references/citations, section-level edges |
| Domain-specific lifecycle columns | Neutral optional facets defined in config |
| No query CLI for code; skill loaded whole CSVs | Query library + CLI + MCP over a derived SQLite/FTS5 store |
| No incremental analysis; no golden tests; silent caps; `>=` dependency ranges | Content-hash incremental with full-rebuild equivalence; golden corpus; announced, configurable caps; lock file + offline bundle |

---

## 2. Principles (every module obeys these)

1. **No model in the build.** Generation is pure code. AI reads the output; it never produces it.
2. **Every file lands somewhere.** A file is a node in the catalog even if nothing could be parsed; its tier and reason are recorded.
3. **Grade every claim.** Every symbol and edge has `tier` (A/B/C/D) and `confidence` (`high`/`medium`/`low`) plus `evidence`. Unresolved and ambiguous references are stored, not dropped.
4. **Absence is never silent.** Skips, failures, caps and truncations are recorded with reasons and counted in coverage.
5. **Deterministic by construction.** Same inputs and same engine version give byte-identical artifacts on any OS. No timestamps or machine paths inside identity hashes.
6. **Read-only on sources.** ContextMAX never writes into the project except under `.contextmax/` and the skill/config files the user asked it to install.
7. **Offline is a requirement.** No network during indexing, querying or viewing. Grammar and dependency provisioning happen once at install time or from an offline bundle.
8. **Cite or say "not checked".** Every query result carries a `cite` string (`src/app.py:42-68`, `docs/spec.pdf p.12 §3.1.2`). The skill must cite what it found and say what it did not look at.
9. **Config holds the vocabulary.** Domain names, id patterns, unit lists, stop words, facets and roles live in `.contextmax/config.json`, never in engine code.
10. **Counts are never capped.** Drawings and previews may be trimmed, but every reported number is the full number, and every trim says so.

---

## 3. Repository layout

```
ContextMAX/
  pyproject.toml            # package metadata, console script, extras
  README.md                 # what it is, install, 5-minute tour
  LICENSE                   # Apache-2.0, copyright Vsevolod Kiriouchine
  NOTICE                    # Apache-2.0 attribution notice
  CHANGELOG.md
  docs/
    PLAN.md                 # this plan, kept current with status boxes
    how-it-works.md         # machinery reference (written as phases land)
    adopting.md             # user guide: install, index, skill, MCP, viz
    decisions/ADR-000x-*.md # one file per architectural decision
    schema/                 # JSON Schemas: config, node, edge, manifest
  src/contextmax/
    __init__.py  __main__.py  cli.py  pipeline.py  version.py
    config.py               # load, defaults, validate (stdlib validator, draft-07 subset)
    discover.py             # walk, ignore rules, skip marker, placeholders, detection
    registry/languages.json # ext/shebang/filename -> language -> grammar, plugin, tags
    registry/formats.json   # ext -> adapter, kind, determinism class
    registry/__init__.py
    model/ids.py  model/nodes.py  model/edges.py   # dataclasses + JSON Schema export
    io/jsonl.py  io/canon.py  io/atomic.py  io/hash.py
    code/base.py            # LanguagePlugin contract + AnalysisResult
    code/treesitter.py      # grammar loading (no download at index time), tags queries
    code/lexical.py         # tier C universal analyzer
    code/resolve.py         # cross-file resolution, candidates, confidence
    code/plugins/python.py  javascript.py  c.py  cpp.py  java.py  csharp.py  go.py
                 rust.py  vhdl.py  verilog.py  matlab.py  shell.py  powershell.py ...
    docs/base.py            # FormatAdapter contract + DocumentTree
    docs/adapters/markdown.py plain.py html.py rst.py asciidoc.py pdf.py ooxml.py
                  odf.py sheet.py csv.py latex.py bibtex.py notebook.py epub.py
                  rtf.py email.py legacy_office.py image.py
    docs/structure.py       # outline tree, TOC, sections, blocks
    docs/terms.py           # defined terms, acronyms, keyphrases (deterministic)
    docs/refs.py            # citations, bibliography, links, cross-refs, id mentions
    docs/params.py          # named quantities and spreadsheet parameters
    link/doc_doc.py  link/doc_code.py  link/code_doc.py  link/file_file.py  link/confidence.py
    graph/build.py  graph/layout.py  graph/cluster.py
    query/store.py          # build query.sqlite (FTS5) from JSONL
    query/api.py            # pure query functions used by CLI and MCP
    query/render.py         # json / table output, cite strings
    mcp/server.py           # stdio MCP server over query.api
    skill/render.py  skill/hosts.json  skill/templates/ (SKILL.md, references/*.md, merge blocks)
    viz/render.py  viz/assets/app.js  viz/assets/app.css   # inlined at render time
    manifest.py  coverage.py  buildstate.py  doctor.py  bootstrap.py  grammars.py
  tests/
    unit/  golden/  determinism/  cli/  mcp/  browser/  security/
    fixtures/corpus/        # synthetic mixed project: every language and format sample
    fixtures/golden/        # committed expected artifacts for the corpus
  scripts/
    make_offline_bundle.py  # wheels + grammar cache + installers -> zip
    update_golden.py
  installers/install.ps1  installers/install.sh   # thin wrappers over python -m contextmax.bootstrap
  .github/workflows/ci.yml
  .gitignore  .contextmax-skip
```

---

## 4. Generated index layout (`<project>/.contextmax/`)

```
.contextmax/
  config.json          # the only committed file (gitignore template: .contextmax/* !config.json)
  .contextmax-skip     # marker: never index this folder (also honoured anywhere in a tree)
  README.md            # generated: what every file here is (for humans and agents)
  INDEX.md             # generated front door: project summary, folders, languages, documents, entry points
  manifest.json        # provenance, identity hashes, completeness, engine/adapter versions
  build-state.json     # stage ledger saved after every stage
  coverage.json        # counts by tier, language, format, adapter, determinism class
  skipped.jsonl        # every excluded or failed file with a reason
  nodes/files.jsonl    symbols.jsonl  documents.jsonl  sections.jsonl  terms.jsonl  references.jsonl  parameters.jsonl
  edges/calls.jsonl    imports.jsonl  contains.jsonl  links.jsonl     # all share one edge envelope
  graph/graph.json     # overview + full graphs with deterministic coordinates
  code/CODEMAP.md      # generated markdown catalog per module (signatures, docs, callers/callees)
  docs/DOCMAP.md       # generated markdown catalog per document (outline, refs, terms)
  text/<docid>.txt     # extracted text cache (bulk; excluded from sharing by default)
  cache/<sha>.<adapter>.json   # per-file analysis cache for incremental refresh
  query.sqlite         # derived FTS5 store; rebuilt on demand; outside identity
  viz/index.html  code.html  code-network.html  docs.html  docs-network.html  links.html
  skill/<name>/SKILL.md + references/   # rendered skill before install; <name>.zip for Claude Desktop
  logs/
```

Config option `output_dir` moves everything except `config.json` to an external folder (for synced or huge projects); `.contextmax/index-path.txt` then points at it.

---

## 5. Data model

### 5.1 Ids (stable across line shifts, human-readable, greppable)

| Kind | Id form | Notes |
|---|---|---|
| file | `file:<relpath>` | forward slashes, NFC-normalized, relative to project root |
| code symbol | `sym:<relpath>#<qualified.name>` | overloads/duplicates get `~2`, `~3` ordinal by source order; line lives in `span` |
| document | `doc:<relpath>` | |
| section | `doc:<relpath>#<sectionpath>` | `sectionpath` = heading number if present (`3.1.2`) else slug chain (`intro/setup`), duplicates get `~n` |
| term | `term:<normalized-term>` | lowercase, hyphenated |
| reference | `ref:<relpath>#<key-or-ordinal>` | citation key, `[12]`, or `r7` |
| parameter | `param:<relpath>#<sheet>!<cell>` or `param:<doc>#<section>~<n>` | |
| module/folder (viz) | `mod:<relpath-of-folder>` | derived, not stored as a node file |

A `content_hash` (normalized body) is stored on symbols and sections so a later `diff` command can detect moves and renames.

### 5.2 Node envelope (all `nodes/*.jsonl`)

```json
{"id":"sym:src/app.py#Thing.run","kind":"function","family":"code","name":"run","qualname":"Thing.run",
 "file":"src/app.py","lang":"python","span":{"start":42,"end":68},"tier":"A","adapter":"python-ast-v1",
 "signature":"def run(self, x: int = 3) -> None","params":[{"name":"x","type":"int","default":"3"}],
 "returns":"None","doc":"First docstring paragraph.","decorators":["@cached"],"visibility":"public",
 "role":"product","parent":"sym:src/app.py#Thing","content_hash":"…","n_lines":27,"cite":"src/app.py:42-68"}
```

Code kinds: `module`, `class`, `struct`, `interface`, `enum`, `function`, `method`, `constructor`, `lambda`, `variable`, `constant`, `field`, `parameter`, `type`, `macro`, `entity`, `architecture`, `package`, `signal`, `port`, `namespace`. Tier C emits `function`/`variable` with `confidence: low`.

Document kinds: `document` (title, format, adapter, determinism, pages, chars, `toc_source`), `section` (depth, number, title, parent, order, `text_range` char offsets into the text cache, page), `table`/`figure` (caption, section), `footnote`, `term` (label, variants, acronym, `method`: defined-term / acronym / glossary / keyphrase / heading, `defined_in`, `occurrences`), `reference` (style: bibtex / numbered / author-year / url / path / doc-id / crossref; raw, key, title, authors, year, doi, url, `resolved`, `candidates`), `parameter` (label, `label_norm`, value, display, unit, formula, `source_kind`, header, hidden).

### 5.3 Edge envelope (all `edges/*.jsonl`)

```json
{"src":"sym:src/main.py#main","dst":"sym:src/app.py#Thing.run","rel":"calls","tier":"A","confidence":"high",
 "count":3,"sites":[{"line":50,"col":8},{"line":51,"col":8},{"line":77,"col":4}],
 "evidence":"import-resolved","status":"resolved","candidates":[],"adapter":"python-ast-v1"}
```

`status` ∈ `resolved` | `ambiguous` (dst = chosen candidate or null, `candidates` filled) | `unresolved` (dst null, `dst_name` kept) | `external` (dst is a module/package outside the project, `dst_name` = `os.path.join`).

Relations: code `calls`, `instantiates`, `inherits`, `implements`, `overrides`, `references` (use without call), `assigns`, `imports`, `includes`, `contains`; document `cites`, `links`, `crossref`, `mentions_id`, `mentions_title`, `shares_term`, `shares_parameter`, `shares_symbol`, `mentions_symbol`, `mentions_file`, `documents` (code comment → doc), `mentions_path`; file `depends_on` (derived from imports/includes).

### 5.4 Manifest, coverage, skipped, build state

- `manifest.json`: `engine_version`, `schema_version`, `project_slug`, `generated_utc` (outside identity), `baseline_identity` {config semantic hash, engine hash, sorted `[relpath, sha256]` of every catalogued file}, `baseline_identity_hash`, `artifact_hashes` {relpath → sha256 of every deterministic artifact}, `artifact_identity_hash`, `adapters` used with versions and determinism class, `grammars` used with versions, `completeness` {`verdict`: full/partial, per-stage ok, `n_skipped`, `n_failed`, `n_tier_c`, `n_tier_d`, `n_grammar_missing`, `n_scans_detected`, `n_truncated`}.
- `coverage.json`: counts by language, format, tier, adapter, determinism class, resolution rate per language ("X of Y call sites resolved; N external; M ambiguous"), doc link counts by kind.
- `skipped.jsonl`: `{file, reason_code, reason, size, detected_as}` for every file not fully analysed, including tier D files ("binary", "grammar not provisioned", "exceeds max_file_mb", "cloud placeholder", "excluded by rule", "parse error at line N", "password protected", "scan detected").
- `build-state.json`: `{config_hash, started_utc, stages: {name: {attempted, ok, error, seconds}}}` saved after each stage; invalidated when config hash changes.

Inside identity: all `nodes/`, `edges/`, `graph/`, `text/`, `CODEMAP.md`, `DOCMAP.md`, `INDEX.md`, `viz/*.html`, `skill/`. Outside: `manifest.generated_utc`, `build-state.json`, `logs/`, `cache/`, `query.sqlite`, `README.md`.

---

## 6. Pipeline (`contextmax index`)

| # | Stage | Module | Reads | Writes | Why here |
|---|---|---|---|---|---|
| 0 | Load config, resolve root, start ledger | `config`, `buildstate` | `config.json` | `build-state.json` | fail fast on invalid config |
| 1 | Discover | `discover` | filesystem | `nodes/files.jsonl`, `skipped.jsonl` (partial) | one catalog row per file, tier assigned, hashes computed |
| 2 | Code analysis | `code/*` | files by language | `nodes/symbols.jsonl`, `edges/calls.jsonl`, `edges/imports.jsonl`, `edges/contains.jsonl`, `cache/` | per-file, cached by content hash; resolution project-wide after all files |
| 3 | Document extraction | `docs/adapters/*`, `structure`, `terms`, `refs`, `params` | files by format | `nodes/documents.jsonl`, `sections.jsonl`, `terms.jsonl`, `references.jsonl`, `parameters.jsonl`, `text/` | needs the symbol index from stage 2 for doc→code links later |
| 4 | Linking | `link/*` | stages 2–3 | `edges/links.jsonl` | doc↔doc, doc↔code, code→doc, file↔file; confidence graded |
| 5 | Graph + layout | `graph/*` | nodes, edges | `graph/graph.json` | deterministic coordinates are part of the artifact |
| 6 | Catalogs | `pipeline` | all | `INDEX.md`, `CODEMAP.md`, `DOCMAP.md`, `README.md` | AI/human-readable front doors |
| 7 | Query store | `query/store` | JSONL | `query.sqlite` | derived; not hashed |
| 8 | Visualization | `viz/render` | JSONL, graph | `viz/*.html` | mirrors the data files exactly |
| 9 | Skill render | `skill/render` | manifest, config | `skill/` | install is a separate explicit command |
| 10 | Manifest + coverage | `manifest`, `coverage` | everything | `manifest.json`, `coverage.json` | must be last: it hashes every artifact |

Every stage is wrapped; a failure is recorded, later stages still run where possible, and the run exits non-zero with a "finished with N problems" summary. A failed stage overrides stale artifacts from a previous run in the completeness verdict.

---

## 7. Discovery and configuration

- **Root**: `contextmax init [path]` creates `.contextmax/config.json`. All commands find the root by walking up from cwd to the nearest `.contextmax/`, or `--root`, or `CONTEXTMAX_ROOT`.
- **Any folder or file**: the config may list several `roots` (folders and individual files, inside or outside the project tree; outside roots are keyed as `ext:<rootid>/<relpath>`). `cmx index <file.pdf>` with no config creates an ad-hoc index next to the file so a single document or script can be indexed and queried. `cmx index --only <glob>` re-analyses a subset; partial runs never prune cache or text entries and say so in `build-state.json`.
- **Ignore rules**, in order: `.contextmax-skip` marker (subtree), `.gitignore` files (parsed with a stdlib-only gitignore matcher; on by default, `respect_gitignore: false` to disable), built-in defaults (`.git`, `node_modules`, `.venv`, `__pycache__`, build outputs, `.contextmax`), config `exclude` globs, config `include` overrides. Every exclusion is recorded in `skipped.jsonl` at summary level (counts per rule) with `--list-excluded` to expand.
- **Detection** (`registry/languages.json`, `registry/formats.json`): extension → shebang → well-known filename (Makefile, Dockerfile, CMakeLists.txt) → content sniff (XML/JSON/NUL-binary). Result: `language` or `format`, `grammar` name, `plugin` id, `tags_available`, `adapter`, `determinism`. Unknown text → language `text`, tier C. Binary → tier D.
- **Safety**: cloud placeholders (Windows attributes `OFFLINE`/`RECALL_ON_DATA_ACCESS`; macOS `.icloud` stubs) never read; `max_file_mb` (default 64) and `max_lines` (default 50 000) caps announced; symlink loops guarded; long paths handled with `\\?\` on Windows.
- **Config schema** (`docs/schema/config.schema.json`, `schema_version: 1`, unknown keys rejected with a path): `project {slug, name, description, keywords}`, `output_dir`, `respect_gitignore`, `include`, `exclude`, `roles [{match, role}]` (product/test/generated/vendor/docs/build), `languages {overrides: {ext: lang}, disabled: []}`, `documents {max_file_mb, max_lines, sheet_max_rows, sheet_max_cols, stopwords_extra, units_extra, modal_words, id_patterns, facets {name: [{match, value}]}, min_symbol_length, generic_term_share, max_owners}`, `graph {max_full_nodes, max_cluster}`, `viz {max_page_mb}`, `skill {name, hosts []}`, `mcp {enabled}`, `features {code, documents, links, viz, skill}`.
- `contextmax init --analyse` samples the tree and **proposes** id patterns and roles from token shapes; nothing is written until confirmed (`--yes` accepts proposals meeting the same bar).

---

## 8. Code analysis

### 8.1 Plugin contract (`code/base.py`)

```python
class LanguagePlugin(Protocol):
    id: str                 # "python-ast-v1"
    language: str           # "python"
    tier: Literal["A"]
    def analyze_file(self, path, text, ctx) -> FileAnalysis   # symbols, call sites, imports, comments
    def resolve(self, project: ProjectIndex) -> None          # cross-file resolution with candidates
```

`FileAnalysis` = `symbols[]`, `call_sites[]` (`caller`, `callee_name`, `qualifier`, `line`, `col`, `kind`), `imports[]` (`module`, `names`, `alias`, `relative`, `line`), `comments[]` with line ranges, `errors[]`. The generic tier B and tier C analyzers implement the same protocol, so downstream code never branches on language.

### 8.2 Tiers and assignment

| Tier | When | Method | Confidence ceiling |
|---|---|---|---|
| A | a dedicated plugin exists for the language | tree-sitter (or `ast`) + language-specific import/scope resolution | high |
| B | a grammar with a `tags.scm` is provisioned but no plugin | generic captures `@definition.function/method/class/module/interface/type/constant`, `@reference.call/class/implementation`, `@name`, `@doc`; resolution same-file → unique project-wide → ambiguous | medium |
| C | text file, no grammar (or grammar not provisioned) | `code/lexical.py`: identifier tokens; definitions by configurable keyword table (`def function fn func sub proc procedure macro defun task entity module class struct interface trait impl type record` + `name(` at line start followed by `{`/`:`/`=`/`is`/`begin`); calls = `identifier(` not in a definition; comments/strings blanked by common delimiters | low |
| D | binary or unreadable | file node only; incoming `mentions_path` edges from other files; `skipped` reason | n/a |

Tier is recorded per file (`nodes/files.jsonl`), per symbol and per edge. Coverage reports counts per tier and lists tier C/D files so the user can provision a grammar or add a plugin.

### 8.3 Resolution (`code/resolve.py`)

1. Build `by_qualname`, `by_name`, `by_file` maps project-wide.
2. Per call site: plugin-specific resolver first (imports, `self`/`this`, receiver types from annotations where cheap, module paths); then same file; then same folder; then unique project-wide; else ambiguous with all candidates listed (sorted by id); else external if the qualifier matches an import of a non-project module; else unresolved.
3. Edges keep `count` and `sites`; `evidence` names the rule that fired.
4. Resolution rate per language goes to `coverage.json` and is printed: "python: 1 204 of 1 350 call sites resolved (89%), 96 external, 31 ambiguous, 19 unresolved".

### 8.4 Tier A plugin order (one plugin per session, each with golden tests)

Python (reference: `ast` + tree-sitter for comments/positions; relative and absolute imports, `__init__` packages, decorators, class attributes, module-level calls, lambdas) → JavaScript/TypeScript (ESM/CommonJS, index resolution, `tsconfig` paths, classes, arrow functions, JSX) → C/C++ (`#include` resolution against project headers, prototypes, macros recorded as `macro`, method definitions `Class::method`) → Java → C# → Go → Rust → VHDL/Verilog/SystemVerilog (entities, ports, signals, instantiations as `instantiates`, packages, `use`) → MATLAB/Octave → Shell/PowerShell/Batch (functions, `source`/dot-sourcing, script invocations as `calls` file-level) → Kotlin/Swift/Ruby/PHP/Lua/Fortran/Julia as tier B until promoted.

### 8.5 Cataloguing internals

Every symbol records signature, parameters (name, type, default, kind), return type, decorators/attributes, docstring or leading comment (first paragraph, normalized whitespace), visibility, parent, `n_lines`, and deterministic size proxies (`n_branches`, `n_calls_out`). Variables and constants record scope, type, literal value preview (≤ 80 chars), and `references` edges (assign/use) so "where is this variable used" is answerable. `CODEMAP.md` renders one section per module: symbol table, docs, callers/callees counts, entry points (product-role symbols with no product callers, labelled "no mapped caller", never "dead").

### 8.6 Grammar provisioning (`grammars.py`)

`tree-sitter-language-pack` (MIT, prebuilt wheels, ~370 grammars) downloads grammars on first use by default. ContextMAX therefore:
- sets the pack cache to `~/.contextmax/grammars/` (override `CONTEXTMAX_GRAMMAR_DIR`) and **disables download at index time**; a missing grammar is a recorded skip reason and the file drops to tier C;
- provisions with `contextmax grammars fetch [--for-project | --all | --from <bundle>]` during install/doctor, or from the offline bundle;
- falls back to the official per-language PyPI wheels (`tree-sitter-python`, `-javascript`, `-c`, …) for the core set when the pack is unavailable.

---

## 9. Document analysis

### 9.1 Adapter contract (`docs/base.py`)

```python
class FormatAdapter(Protocol):
    id: str; version: str; determinism: str; extensions: tuple[str, ...]
    def available(self) -> tuple[bool, str]         # dependency present? reason if not
    def extract(self, path, ctx) -> DocumentTree     # or ExtractionError(reason)
```

`DocumentTree` = metadata (title, authors, date, language hint, pages) + ordered blocks: `heading(depth, text, number)`, `paragraph`, `list_item`, `table(rows)`, `code(lang, text)`, `figure(caption)`, `footnote(id, text)`, `link(target, text)`, `citation(marker, keys)`, `math`, `page(n)`, `cell` (sheets), `notebook_cell(kind, n)`. `docs/structure.py` turns blocks into the outline tree, section text ranges, TOC (explicit from PDF outline / DOCX TOC field / Markdown TOC if present, else derived; `toc_source` recorded), tables/figures/footnotes lists, and the text cache rendering (headings as `#` lines, tables tab-separated, one cell per line for sheets).

Code inside documents (Markdown fences, LaTeX listings, notebook cells) is analysed by the code tiers using the fence language; resulting symbols are flagged `in_document: true`, live under the section id, and are matched against project symbols to produce `mentions_symbol` edges with `evidence: code-block`. Comments and docstrings inside code are scanned by the same `refs.py` so code can point back at documents.

### 9.2 Format registry (all formats land somewhere)

| Formats | Adapter | Determinism | Dependency |
|---|---|---|---|
| md, txt, rst, adoc, org, log | `markdown-v1`, `plain-v1`, `rst-v1`, `asciidoc-v1` | intrinsic | stdlib |
| html, htm, xhtml | `html-v1` (tags stripped, headings/links/tables kept) | intrinsic | stdlib |
| pdf | `pdf-v1` (text, outline/bookmarks as TOC, link annotations, page map, scan detection) | version-bound | `pypdf` (BSD); optional `pdfplumber` (MIT) for tables; optional PyMuPDF extra (AGPL, opt-in) |
| docx/docm/dotx, pptx/pptm/ppsx | `ooxml-v1` (document order, tables, headers/footers, footnotes, comments, TOC field, hyperlinks) | intrinsic | stdlib zip + ElementTree |
| odt/ott/fodt, odp, odg, ods | `odf-v1` | intrinsic | stdlib |
| xlsx/xlsm, xls, ods, csv/tsv | `sheet-v1` (cell records, label-left heuristic, units, formulas, formula literals, header detection, truncation announced) | version-bound / intrinsic | `openpyxl` (MIT), `xlrd` (BSD) |
| tex/ltx/bib | `latex-v1` (sections, labels/refs, `\cite`, includes), `bibtex-v1` (entries) | intrinsic | stdlib |
| ipynb | `notebook-v1` (markdown cells → sections; code cells → tier-A/B code analysis by kernel language) | intrinsic | stdlib |
| epub | `epub-v1` | intrinsic | stdlib |
| rtf | `rtf-v1` | intrinsic | own small parser or `striprtf` (BSD) |
| eml/mbox | `email-v1` (headers, body, attachments listed) | intrinsic | stdlib |
| json/yaml/toml/xml/ini | `config-v1` (keys as terms, paths and urls as references) | intrinsic | stdlib (+ `tomllib`) |
| doc/xls/ppt (legacy binary) | `legacy-office-v1`: LibreOffice headless if present, else Word COM on Windows, else catalog-only with reason | environment-bound | optional |
| images | `image-v1` catalog-only with dimensions/EXIF if Pillow present; OCR never by default | catalog-only | optional |
| everything else | catalog-only with reason; text-looking files fall to `plain-v1` | catalog-only | — |

Zip-bomb guards on every package format; password-protected files recorded as such; scans flagged when < 60 chars/page.

### 9.3 Terms and concepts (`docs/terms.py`, all deterministic)

- Defined terms: `X (ABC)` acronym introductions; `"X" means`, `X is defined as`, `X: definition`; glossary/abbreviation tables (2-column tables under headings matching a configurable list); Markdown definition lists; LaTeX `\newacronym`/`\gls`.
- Keyphrases: candidate n-grams (1–4 tokens, stopword-filtered, configurable stopword list with English defaults) scored by corpus TF-IDF with fixed rounding and `(−score, term)` tie-break; per-document cap announced (`terms_cap`, default 40).
- Headings as topics; capitalized multiword sequences as named entities candidates (`method: capitalized`).
- Each term records `method`, `defined_in` (section ids), `occurrences` (section ids with counts), corpus document frequency.

### 9.4 References and citations (`docs/refs.py`)

- Bibliography section detection (heading matches `references|bibliography|works cited|literature`, configurable) → entries split by numbering `[n]`, `n.`, or blank lines → fields parsed heuristically (authors, year, title, DOI, URL); `.bib` files parsed exactly.
- In-text citations: `[12]`, `[3, 5–7]`, `(Smith et al., 2020)`, `\cite{key}`, footnote markers, Markdown/HTML links, `see Section 3.2`, `Figure 4`, `Table 2`, doc ids by config pattern, file paths and URLs.
- Resolution: citation → bib entry (by key/number) → project document (by DOI, then normalized title, then filename stem, then URL path); relative links → files/sections; external targets kept with `resolved: null` and `external: true`. Confidence: exact key/DOI/path = high; title match = medium; stem or partial = low. Ambiguity keeps candidates.

### 9.5 Parameters (`docs/params.py`)

Spreadsheet cells as in the predecessor (label from nearest text cell to the left, unit from `[unit]` or a cell to the right through a configurable alias table, formulas kept, formula literals as separate unit-less rows, hidden cells flagged). Prose quantities: number + unit from a configurable unit list, with the nearest preceding label. "Parameter identity is the label, not the number"; `cmx q param --compare <label>` reports agreement per document.

---

## 10. Linking (`link/*`)

| Edge | Rule | Confidence |
|---|---|---|
| doc `cites` doc | resolved citation/bib entry | high (key/DOI/path), medium (title), low (stem) |
| doc `links` doc/section/file | relative link or anchor resolved | high |
| doc `crossref` section | internal "Section 3.2" / label refs | high |
| doc `mentions_id` doc | configured id pattern found in text, owner unique | high; `ambiguous` if several owners |
| doc `mentions_title` doc | another document's title (≥ 3 words) verbatim | medium |
| doc `shares_term` doc | ≥ `min_shared_terms` (default 3) non-generic terms | low–medium by count |
| doc `shares_parameter` doc | same `label_norm` (≥ 2) | medium |
| section `mentions_symbol` symbol | symbol token in section text (min length configurable, default 4); inline code spans or qualified names count double | 1 → low, 2–4 → medium, ≥ 5 → high (per section) |
| section `mentions_file` file | path or filename with extension in text | high |
| symbol/file `documents` doc | comment or docstring contains a doc path, URL or id | high |
| file `depends_on` file | derived from imports/includes | inherits |
| file `mentions_path` file | path string in any text file | medium |

Generic suppression: a term or label owned by more than `min(max_owners=40, 50% of documents)` documents is not used for `shares_*`. Per-document cap on `shares_*` edges (default 12) ranked by `(−weight, src, dst)`. Proportional thresholds are sanity-checked at 10× scale in tests.

---

## 11. Graph and visualization

### 11.1 `graph/graph.json`

- `overview`: nodes = code modules (folder-derived, `mod:` ids) and document groups (folder or facet); edges condensed with weights; layered layout (iterative sorted DFS back-edge removal, longest-path rank, four fixed barycentre passes with stable sort, fixed spacing constants).
- `code_full`, `docs_full`, `links`: every node with cluster boxes (clusters subdivided along real path segments above `max_cluster`, column-major grid ordered by port side); capped at `max_full_nodes` (default 5 000) by **degree then id**, with `truncated` count and the rule stated.
- Per-node `callers`, `callees`, `tier`, `role`, `lang`, `loc`; per-edge `rel`, `confidence`, `weight`.
- No RNG; positions hashed; shuffled-input test.

### 11.2 Pages (single-file, data inlined, zero external URLs)

| Page | Shows |
|---|---|
| `index.html` | completeness banner, stats, coverage by tier/language/format, top skipped reasons, links to everything |
| `code.html` | module overview → pick a symbol → neighbourhood (callers left, focus centre, callees right), hop depth 1/2/3/all, direct and transitive counts always exact, tier/role/confidence filters, search box, source citation |
| `code-network.html` | whole code graph with clusters; Canvas renderer above 2 000 nodes, SVG below; hover/click details |
| `docs.html` | document list with facets → outline tree, TOC, terms, references, parameters, links to sections; deep link `#doc=…`/`#sec=…` |
| `docs-network.html` | whole document graph by edge kind with kind filters |
| `links.html` | doc ↔ code bipartite view; pick a section or symbol to see the other side |

Recommendation: **hand-rolled SVG + Canvas, no third-party JavaScript.** Layout is already computed in Python, so the browser only needs rendering, pan/zoom, search, filtering and neighbourhood walks (≈ 1 500 lines of vanilla JS in `viz/assets/app.js`). This keeps pages small, deterministic, license-clean and offline. If pan/zoom or hit-testing proves inadequate, vendor a pinned copy of `d3-zoom` (ISC) inline; never a physics/force library. Each page is rendered from the same JSONL the CLI reads, and a test asserts the counts on the page equal the counts in `coverage.json`. Page size ceiling (`viz.max_page_mb`, default 25) triggers a "lite" page that omits full-network data and says so.

---

## 12. Query layer, CLI and MCP

### 12.1 `query/api.py` (pure functions, dict results, every hit has `cite`)

`status`, `search(q, kinds, lang, limit)` (FTS5 over names, docstrings, section text), `find_symbol(name, lang, kind)`, `symbol(id)`, `callers(id, depth, roles)`, `callees(id, depth)`, `impact(id, depth)` (transitive with seen-set; direct and total counts; product vs test split; boundary note listing external/unresolved), `file(path)`, `file_deps(path, direction)`, `find_document(q)`, `document(id)`, `outline(id)`, `section(id, text=True)`, `related(id, rels)`, `term(q)`, `parameter(label|value, compare)`, `references(doc)`, `skipped(reason)`, `source(id|path, start, end)` (exact lines with citation), `explain(src, dst)` (why this edge exists).

### 12.2 CLI (`contextmax` / `cmx`)

```
cmx init [path] [--analyse] [--yes]          cmx index [--full] [--stage …] [--quiet]
cmx refresh                                  cmx status [--json]      cmx doctor [--json]
cmx q search "servo error"                   cmx q symbol Thing.run   cmx q callers Thing.run --depth 2
cmx q impact Thing.run                       cmx q file src/app.py    cmx q deps src/app.py --reverse
cmx q doc "spec"                             cmx q outline docs/spec.pdf     cmx q section "docs/spec.pdf#3.1.2" --text
cmx q related "doc:docs/spec.pdf"            cmx q term glossary      cmx q param "servo error" --compare
cmx q skipped --reason grammar               cmx q source src/app.py:42-68
cmx skill render | install --host claude-code-project [--host …] | list-hosts
cmx mcp serve                                cmx mcp config --host claude-desktop|claude-code|vscode|cursor
cmx viz open [page]                          cmx grammars fetch|list|status
cmx verify                                   cmx export --format graphml|csv|obsidian
cmx clean [--cache] [--all]
```

`--json` is the default when stdout is not a TTY (agents), tables otherwise. Exit codes: 0 ok, 1 problems, 2 usage, 3 no index. `cmx verify` recomputes every artifact hash and the source hashes, compares them with `manifest.json`, and reports which artifacts drifted and which sources changed since the baseline, so a stale index is detectable without rebuilding.

### 12.3 MCP server (`mcp/server.py`, official `mcp` SDK v2, stdio)

Tools `cmx_status`, `cmx_search`, `cmx_find_symbol`, `cmx_symbol`, `cmx_callers`, `cmx_callees`, `cmx_impact`, `cmx_file`, `cmx_file_deps`, `cmx_find_document`, `cmx_document_outline`, `cmx_section`, `cmx_related`, `cmx_term`, `cmx_parameter`, `cmx_references`, `cmx_skipped`, `cmx_source`, `cmx_explain`; resources `contextmax://manifest`, `contextmax://coverage`, `contextmax://index-md`. Every tool description states the tier/confidence semantics and that results are pointers to be verified in the source. `cmx mcp config` prints or writes the host snippet (`claude_desktop_config.json` `mcpServers`, `.mcp.json` for Claude Code, `.vscode/mcp.json`, `.cursor/mcp.json`). Tested with the SDK's in-memory client.

---

## 13. Skill and agent-instruction generation

- Skill follows the Agent Skills specification: `name` (1–64 chars, lowercase, hyphens, equals folder name → `contextmax-<slug>`), `description` (≤ 1024 chars, includes trigger keywords from config), `metadata` (engine version, index path hint, baseline hash), `compatibility` only when needed. `SKILL.md` stays under 500 lines; details go to `references/recipes.md`, `references/schema.md`, `references/honesty.md`, `references/mcp.md`.
- **Finding the index** (Step 0): run `cmx status --json` from the project (walks up to `.contextmax/`); else `index-path.txt` sidecar next to the installed skill; else `CONTEXTMAX_ROOT`; else ask. Then read `manifest.completeness` and the baseline date for the trust footer.
- **Answer contract**: (1) Code findings cited `file:line-range`; (2) Document findings cited `document p./§section`; (3) "Documentation: not checked" when no document was opened; (4) one verdict Agree / Doc-only / Code-only / Conflict for "how does X work" questions; quick lookups exempt. Trust footer once per chat: `contextmax-<slug>: baseline <date> · <full|partial> · tiers A/B/C/D coverage · confidence <High|Medium|Low> (<reason>)`.
- **Honesty rules**: the index is a fast way in, not the truth; tier C/D and low-confidence edges are leads, not facts; check `cmx q skipped` and coverage before claiming absence; verify every load-bearing claim by opening the cited source with `cmx q source`; never claim code compiles or that a document normatively specifies code.
- **Recipes** map each task to one CLI command or MCP tool (find a document, locate a symbol, impact analysis, read a section, relate doc and code, quantity provenance, what is not indexed).
- **Host registry** (`skill/hosts.json`, data only):

| Host | Destination | Layout |
|---|---|---|
| `claude-code-project` / `claude-code-user` | `.claude/skills/<name>/` / `~/.claude/skills/<name>/` | skill folder + `index-path.txt` |
| `claude-desktop` | `.contextmax/skill/<name>.zip` for upload via Settings → Skills, plus `cmx mcp config --host claude-desktop` | zip + MCP snippet |
| `copilot-project` / `copilot-user` | `.github/skills/<name>/` / `~/.copilot/skills/<name>/` | skill folder |
| `cursor` | `.cursor/skills/<name>/` (Cursor also reads `.claude/skills`) | skill folder |
| `codex` | `.codex/skills/<name>/` or `~/.codex/skills/<name>/` | skill folder |
| `windsurf` | `.windsurf/skills/<name>/` | skill folder |
| `agents-md` / `claude-md` / `copilot-instructions` | `AGENTS.md` / `CLAUDE.md` / `.github/copilot-instructions.md` | merge block between `<!-- contextmax:<slug> begin/end -->` markers, idempotent |
| `custom` | `--path` | skill folder or single file |

Values are YAML-escaped when rendered; files are written UTF-8 without BOM; unfilled placeholders fail the render. Host conventions are re-verified against current docs at implementation time.

---

## 14. Determinism, provenance and honesty rules

- All writes go through `io.jsonl` / `io.canon` (sorted keys, sorted rows by explicit key tuples, `ensure_ascii=False`, `\n`, UTF-8 no BOM, atomic temp-and-rename). Canonical hash = SHA-256 of `json.dumps(obj, sort_keys=True, separators=(",", ":"))`.
- Paths: forward slashes, relative, NFC; one `rel_key()` used for every pattern match.
- Sorting is ordinal (Python default) and never locale-aware; numbers formatted with fixed rounding; no `Counter.most_common()` without a tie-break.
- Timestamps only in `generated_utc` and logs; machine paths only in `build-state.json`/`README.md`; capability inventories only in `doctor` output.
- Adapter id + version + determinism class on every document and symbol record; grammar versions in the manifest.
- Incremental refresh reuses `cache/` entries keyed by content hash + adapter id + version + relevant config hash; `cmx index --full` must produce identical artifact hashes (CI test).
- Every cap, truncation, skip and failure is announced in output, recorded in `skipped.jsonl` or the record's `notes`, and counted in `coverage.json`.

---

## 15. Packaging and distribution

- `pyproject.toml` (hatchling), package `contextmax`, `license = "Apache-2.0"`, `authors = [{name = "Vsevolod Kiriouchine"}]`, console scripts `contextmax` and `cmx`. Base install is stdlib-only and already indexes tiers C/D and Markdown/plain/HTML/OOXML/ODF/CSV/LaTeX/BibTeX/notebooks/email. Every source file carries a short SPDX header (`SPDX-License-Identifier: Apache-2.0`). All default and extra dependencies must be Apache-compatible (MIT, BSD, ISC, Apache); the only copyleft option is the opt-in `[mupdf]` extra, which `cmx doctor` labels as AGPL when present.
- Extras: `[pdf]` pypdf (+ pdfplumber), `[office]` openpyxl, xlrd, `[code]` tree-sitter + tree-sitter-language-pack, `[mcp]` mcp, `[images]` Pillow, `[mupdf]` PyMuPDF (opt-in, AGPL), `[all]`.
- Lock file with hashes (`uv.lock` + exported `requirements-lock.txt`); `scripts/make_offline_bundle.py` builds `contextmax-offline-<ver>-<os>-<arch>.zip` containing wheels, a grammar cache and `installers/install.ps1|.sh`, which call `python -m contextmax.bootstrap` to create a private venv under `~/.contextmax/venv/`, install with `--no-index --require-hashes`, provision grammars and put `cmx` on the user PATH (no admin rights). Online path: `pipx install "contextmax[all]"` then `cmx grammars fetch`.
- `cmx doctor`: Python version and bitness, extras present/missing (with the formats each unlocks), grammar cache status, index state and completeness, detected AI hosts, output dir not inside a synced folder warning.
- Version stamping in `version.py`; engine hash in the manifest.

---

## 16. Testing and CI

- `tests/fixtures/corpus/`: a synthetic mixed project generated in-process (no real user material): every tier-A language sample with calls across files, a tier-B language, an unknown-language script, a binary, Markdown with TOC/links/footnotes, PDF generated with pypdf or reportlab-free minimal writer, DOCX/PPTX/ODT/ODS built as in-memory zips, an XLSX (skipped if openpyxl missing), LaTeX + BibTeX with citations, a notebook, HTML, EML, config files, locale-hostile filenames, a nested `.contextmax-skip` tree, a cloud-placeholder stand-in.
- `tests/golden/`: committed expected `nodes/`, `edges/`, `coverage.json` for the corpus; `scripts/update_golden.py` regenerates with a diff review.
- `tests/determinism/`: two-run byte equality; shuffled discovery order; incremental vs full equality; hash sensitivity both ways; cross-OS artifact hash compared as a CI job artifact.
- `tests/unit/`: per adapter, per plugin, structure, terms, refs, params, resolve, layout (cycles, deep chains, no node dropped), config validation.
- `tests/cli/` and `tests/mcp/` (in-memory client, every tool schema round-trips).
- `tests/security/`: zip bomb, `</script>` injection, path traversal in links, no external URL in pages, no absolute path in shareable artifacts, password-protected files recorded not crashed.
- `tests/browser/` (optional, Playwright with local Chrome/Edge): each page renders at 1280×800 and 390×844 with zero console errors, counts on page equal `coverage.json`, deep links resolve.
- CI: GitHub Actions matrix `windows-latest`, `macos-latest`, `ubuntu-latest` × Python 3.11 and 3.13; a final job compares the three OS artifact hashes and fails on drift.

---

## 17. Roadmap

"Session" = one focused working session. Estimates are rough; each phase ends with a tagged release, updated `docs/PLAN.md` status, and an ADR for any decision taken.

| Phase | Goal | Deliverables | Acceptance | Sessions |
|---|---|---|---|---|
| 0 Foundations | Repo skeleton and contracts | pyproject, layout, `model/`, `io/`, `config`, `discover`, registries, CI matrix, fixture corpus generator, ADR-0001..0004 (runtime, tiers, ids, index location) | `cmx init` + `cmx status` work on 3 OSes; two-run equality of `nodes/files.jsonl`; config validation errors show JSON paths | 2–3 |
| 1 Walking skeleton | End to end on tiers C/D + Markdown/plain | lexical analyzer, Markdown/plain/HTML adapters, structure, `edges/`, `graph.json` with layout, `INDEX.md`, minimal `index.html` + `code.html`, `cmx q search/symbol/callers/doc/outline`, Claude Code skill render + install, manifest/coverage/skipped/build-state | Index this repo and a sample docs folder; open the page; ask Claude Code a question through the skill and get a cited answer; artifact hash identical across two runs | 3–4 |
| 2 Real code analysis | Tiers A/B, resolution, query store | tree-sitter loading with downloads disabled, `grammars fetch`, tier B tags analyzer, Python tier A plugin, `resolve.py` with candidates, `query.sqlite` FTS5, `impact`/`deps`/`source`/`explain`, `CODEMAP.md`, `code-network.html` | ≥ 90% call-site resolution on the Python corpus, ambiguity recorded, resolution rate printed; golden tests green; incremental == full | 4–6 |
| 3 Documents wave | All document formats and structure | pdf, ooxml, odf, sheet, csv, latex/bibtex, notebook, epub, rtf, email, config, legacy-office, image adapters; TOC/outline; terms; refs; params; `DOCMAP.md`; `docs.html` | Every corpus format yields a document with outline; every unsupported case appears in `skipped.jsonl` with a reason; text cache pruning tested | 6–8 |
| 4 Linking and views | Cross-layer edges and full viz | `link/*`, confidence rules, generic suppression, `links.jsonl`, `docs-network.html`, `links.html`, page counts == coverage test, browser smoke | Corpus produces every edge kind at least once with the expected confidence; no invented edge for an unowned id | 4–5 |
| 5 Language plugins | Tier A breadth | JS/TS, C/C++, Java, C#, Go, Rust, VHDL/Verilog, MATLAB, Shell/PowerShell plugins with golden tests each | Each plugin ≥ 85% resolution on its corpus sample; tier B fallback verified for every remaining pack language | 6–10 |
| 6 Agents everywhere | Skills for all hosts + MCP | `hosts.json` complete, merge blocks, Claude Desktop zip, `cmx mcp serve/config`, MCP tests, answer contract references, `cmx doctor` host detection | Skill validates with `skills-ref`; MCP tools work in Claude Desktop, Claude Code and VS Code; a fresh agent answers with citations and the trust footer | 3–4 |
| 7 Scale and refresh | Large and synced projects | incremental `refresh`, per-file cache, streaming JSONL, external `output_dir`, cloud placeholders, `~/.contextmax/projects.json` registry, 50k-file benchmark | 50k-file synthetic project indexes within budget; refresh after one edit touches one cache entry; artifacts identical to full | 3–4 |
| 8 Product release 1.0 | Installable by anyone | offline bundle, installers, lock file, `pipx` path, docs (`how-it-works`, `adopting`), security tests, cross-OS hash job, CHANGELOG, release tags | Clean-machine install on Windows/macOS/Linux without admin or network (from bundle); `cmx doctor` green; all suites green on the matrix | 3–4 |
| 9 Post-1.0 | Growth | `cmx diff` (moves/renames via content hashes), optional OCR extra, `export` formats, watch mode, more plugins, multi-project federation in the skill/MCP, optional git facet (last author/date per file as visible metadata, outside identity), VS Code extension wrapper around the CLI/MCP | per feature | ongoing |

Total to 1.0: roughly 35–50 sessions.

---

## 18. Risks and open questions (with defaults)

1. **ContextMAX license**: decided, Apache-2.0 with Vsevolod Kiriouchine as author. `pypdf` is the default PDF adapter; PyMuPDF only as an explicit `[mupdf]` extra with an AGPL notice.
2. **Grammar download-on-demand** breaks offline: handled by provisioning at install time, download disabled at index time, offline bundle carries a grammar cache; core grammars also available as per-language wheels.
3. **Dynamic languages resolve imperfectly**: tiers, candidates and printed resolution rates keep this honest; the skill treats low-confidence edges as leads.
4. **PDF bibliography parsing is heuristic**: DOI/URL/key matches are high confidence; title/stem matches are graded down; unresolved entries stay visible as `reference` nodes.
5. **Legacy binary Office** depends on LibreOffice or Word: environment-bound adapters with detection, otherwise catalog-only with reason.
6. **Scale**: JSONL streaming and SQLite keep memory bounded; thresholds tested at 10× corpus size; full-network pages capped with the rule stated.
7. **Tree-sitter grammar quality varies** (some lack `tags.scm`): those languages go to tier C until a plugin exists; coverage lists them.
8. **Cross-OS byte identity** (CRLF checkouts, NFD filenames, path length): hash source bytes as-is, NFC keys, long-path prefix on Windows, CI cross-OS hash job catches drift.
9. **Skill host conventions move**: registry is data; re-verified at Phase 6.
10. **OCR**: out of scope until post-1.0; scans are detected and listed.

---

## 19. Verification (how each phase is checked end to end)

1. `cmx init --analyse` on `tests/fixtures/corpus` and on the ContextMAX repo itself; confirm proposals, then `cmx index`.
2. `cmx status --json` shows `completeness.verdict` and per-tier counts; `cmx q skipped` lists every excluded file with a reason.
3. Run `cmx index --full` twice and compare `manifest.artifact_identity_hash`; run `cmx refresh` after editing one file and compare again to a fresh full build.
4. Query round trip: `cmx q symbol`, `callers`, `impact`, `doc`, `outline`, `section --text`, `related`, `source`; every result has a `cite` that opens the right lines.
5. `cmx skill install --host claude-code-project`, then ask Claude Code "how does X work" and check the four-part answer, citations and trust footer; `cmx mcp config --host claude-desktop`, restart Claude Desktop, call `cmx_impact`.
6. Open `viz/index.html` offline (network disabled); counts equal `coverage.json`; click through code → docs → links deep links.
7. Full test suite on Windows locally and the three-OS CI matrix; cross-OS hash job green.

## 20. First implementation session (after approval)

1. Commit this plan as `docs/PLAN.md`, add `LICENSE` (Apache-2.0 text) and `NOTICE` naming Vsevolod Kiriouchine, write ADR-0001 (runtime and platform), ADR-0002 (analysis tiers), ADR-0003 (id scheme), ADR-0004 (in-project index), ADR-0005 (license and dependency policy), and the initial README.
2. Create `pyproject.toml`, `src/contextmax/` skeleton, `model/`, `io/`, `config.py` with schema and validator, `registry/*.json`, `discover.py`, `cli.py` with `init`/`status`/`doctor`.
3. Write the fixture corpus generator and the determinism test harness; wire the CI matrix.
4. Tag `v0.0.1` when `cmx init` and `cmx status` produce a deterministic `nodes/files.jsonl` on the corpus.
