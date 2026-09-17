# Phase 1 — Walking skeleton

Status: in progress (started 2026-09-17). Builds on Phase 0 (`v0.0.1`).

## Goal

After Phase 1 a person or an agent can ask real questions of a project and get cited answers,
end to end, using only what a base install can do: tier C lexical code analysis, text-based
document formats, links between them, a query CLI, three offline HTML pages and a Claude Code
skill. Everything later (grammars, PDF, spreadsheets, MCP, more hosts) plugs into the files
and interfaces defined here without changing their shape.

The running example is the master project archive (149 MATLAB files of which 119 are scripts,
7 LaTeX files with sections, labels, cross-references, figures and citations but no `.bib`,
5 saved HTML pages, plus `.aux`/`.log`/`.txt`). Phase 1 is done when the acceptance list at the
end passes on the fixture corpus and on that archive.

## Scope

In: lexical code analysis for every text language; Markdown, plain text, HTML and LaTeX
adapters (LaTeX pulled forward from Phase 3 because the example needs it and it is regex work);
document structure and a text cache; references (links, cross-references, citations,
includes); code and document links; graph data with deterministic layout; catalogs; the SQLite
query store; the `cmx q` commands; `index.html`, `code.html`, `docs.html`; the Claude Code
skill; golden and determinism tests; CI stays green on three operating systems.

Out (later phases): tree-sitter tiers A/B, PDF, Office and spreadsheets, terms and concepts,
parameters, the network and links pages, MCP, other skill hosts, incremental refresh.

## Deliverables

### 1. Code analysis contract and tier C (`src/contextmax/code/`)

- `base.py`: `LanguagePlugin` protocol (`id`, `language`, `tier`, `analyze_file`, `resolve`) and
  the result types `Symbol`, `CallSite`, `Import`, `Comment`, `FileAnalysis`. Tier B and tier C
  analyzers implement the same protocol so nothing downstream branches on tier.
- `registry/lexical.json`: per-language lexical profiles (data, not code): line and block
  comment delimiters, string delimiters, definition patterns with named groups (`kind`, `name`,
  `params`, `returns`), call syntax, import patterns, region markers, a `default` profile for
  unknown text. First profiles: matlab, python, javascript/typescript, c/cpp, java, csharp, go,
  rust, shell, powershell, batch, css, sql, vhdl, verilog, default.
- `lexical.py` (`lexical-v1`): blanks comments and strings while preserving line count (so
  every `file:line` is exact), captures definitions, module-level and function-level call sites
  with line and column, imports, leading comment or docstring as `doc`, parameters and return
  names parsed from the signature, `%%` / `# %%` / `#region` markers as `region` symbols, and a
  `script` symbol for files with no definitions (MATLAB scripts are callable by name and must be
  nodes). Span end is heuristic (next definition at the same or lower indentation, or a
  language end keyword); `span.end_exact: false` says so.
- `resolve.py`: project-wide resolution with candidates. Order: plugin resolver (none yet),
  same file, same folder, unique project-wide, MATLAB-style file-by-name (a call `foo(` resolves
  to the `foo` symbol defined in `foo.m` anywhere on the roots), else `ambiguous` with the
  sorted candidate list, else `external` when the name matches an import of a non-project
  module, else `unresolved`. Multiplicity kept (`count`, `sites`). Resolution rate per language
  printed and written to coverage.
- Stage `code` writes `nodes/symbols.jsonl`, `edges/calls.jsonl`, `edges/imports.jsonl`
  (file → file when resolved, else `dst_name`), `edges/contains.jsonl` (file → symbol, parent →
  child). Every row carries `tier: "C"`, `confidence: "low"`, `evidence: "lexical"`.
- Coverage gains `code.n_symbols`, `n_call_sites`, `n_resolved`, `n_ambiguous`, `n_unresolved`,
  `n_external`, `by_language`.

### 2. Document adapters and structure (`src/contextmax/docs/`)

- `base.py`: `FormatAdapter` protocol (`id`, `version`, `determinism`, `available()`,
  `extract()`), `DocumentTree` (metadata + ordered blocks: heading, paragraph, list_item, table,
  code, figure, footnote, link, citation, label, math, page) and `ExtractionError`.
- Adapters: `markdown-v1` (ATX and setext headings, fenced code with language, tables, links,
  images, footnotes, front matter title), `plain-v1` (paragraphs; underlined headings when
  obvious), `html-v1` (stdlib parser: `h1`–`h6`, `p`, `li`, `pre`, tables, `a href`, `title`;
  scripts and styles dropped), `latex-v1` (`\part` to `\subparagraph`, `\label`, `\ref`/`\eqref`
  /`\autoref`, `\cite*`, `\input`/`\include`/`\bibliography`, `figure`/`table` environments with
  captions, `\title`, comments stripped, math kept as one block). `.aux` and `.log` stay
  `plain-v1`.
- `structure.py`: outline tree from headings (depth from heading level or LaTeX command),
  section ids `doc:<path>#<number-or-slug-chain>` with `~n` for duplicates, section text ranges
  as character offsets into the text cache, derived TOC (`toc_source: derived` until PDF
  outlines arrive), lists of tables and figures with captions, footnotes.
- Text cache: `text/<sha256(key)[:16]>.txt` rendered deterministically (headings as `#` lines,
  tables one row per line with tab-separated cells, code fences kept), plus `text/index.jsonl`
  mapping key → file. Bulk text stays inside the index folder; nothing is written to sources.
- `refs.py` (Phase 1 subset): Markdown and HTML links (relative paths, anchors, URLs), LaTeX
  `\ref`/`\label` cross-references, `\cite` keys, `\input`/`\include`, bare paths and file names
  with extensions found in text. Writes `nodes/references.jsonl` with `resolved` or
  `candidates`, and `external: true` for URLs and citation keys with no bibliography.
- Stage `documents` writes `nodes/documents.jsonl`, `nodes/sections.jsonl`,
  `nodes/references.jsonl`, the text cache and `DOCMAP.md`. Coverage gains `documents.*`.

### 3. Links (`src/contextmax/link/`)

- `doc_doc.py`: `links` (resolved relative link or include), `crossref` (label ↔ ref inside and
  across LaTeX files), `cites` (only when a bibliography resolves; otherwise the reference node
  stays visible as external).
- `doc_code.py`: section → symbol `mentions_symbol` by token intersection with the symbol index
  (min length from config, inline code spans and qualified names count double; confidence low /
  medium / high by distinct symbols) and section → file `mentions_file` for paths and file names.
- `file_file.py`: `depends_on` derived from resolved imports and cross-file calls, and
  `mentions_path` for text files that name another file.
- Stage `links` writes `edges/links.jsonl`; generic-token suppression and per-document caps from
  config apply from the start. Coverage gains `links.*`.

### 4. Graph (`src/contextmax/graph/`)

- `build.py`: overview nodes are folder-derived modules (`mod:` ids) for code and folders for
  documents; condensed weighted edges; per-node counts.
- `layout.py`: iterative sorted DFS back-edge removal, longest-path ranks, four fixed
  barycentre passes with stable sort, fixed spacing; `cluster.py`: grid packing with
  subdivision above `max_cluster`. No random source anywhere.
- Stage `graph` writes `graph/graph.json` (`overview`, `code_full`, `docs_full` capped by degree
  then id with `truncated` reported).

### 5. Catalogs

`INDEX.md` gains entry points (symbols with no mapped caller, labelled as such), the largest
modules and the document list with titles. `CODEMAP.md` renders one section per module with a
symbol table (kind, signature, doc, callers, callees, cite). `DOCMAP.md` renders each document's
outline, references and links.

### 6. Query layer (`src/contextmax/query/`)

- `store.py`: `query.sqlite` built from the JSONL (tables nodes, edges, sections, references;
  FTS5 over symbol names and docs, section titles and text). Derived; rebuilt when the manifest
  hash changes; outside identity.
- `api.py`: `status`, `search`, `find_symbol`, `symbol`, `callers`, `callees`, `impact` (direct
  and transitive with seen-set, product vs test split, boundary note), `file`, `file_deps`,
  `find_document`, `document`, `outline`, `section` (with text), `related`, `references`,
  `skipped`, `source` (exact lines with a citation string), `explain`.
- `cli.py`: `cmx q <verb> …`, JSON by default when stdout is not a terminal, tables otherwise.
  Every result row has `cite` (`src/x.m:12-40`, `docs/guide.tex §3.2`).

### 7. Visualization (`src/contextmax/viz/`)

Single-file pages with data inlined and escaped, zero external URLs, hand-rolled SVG:
`index.html` (completeness banner, coverage by tier/language/format, top skip reasons, links),
`code.html` (module overview laid out from `graph.json`; pick a symbol for callers left, focus
centre, callees right with hop depth 1/2/3/all; counts never capped; search box; source citation),
`docs.html` (document list, outline tree, references, links to sections). A test asserts the
counts shown equal `coverage.json`.

### 8. Claude Code skill (`src/contextmax/skill/`)

- `hosts.json` with `claude-code-project`, `claude-code-user`, `custom`; the other hosts arrive
  in Phase 6 on the same registry.
- Templates render `SKILL.md` (Agent Skills frontmatter: `name` = `contextmax-<slug>`,
  `description` with the project's keywords, `metadata` with engine version and baseline hash;
  body under 500 lines) plus `references/recipes.md`, `references/schema.md`,
  `references/honesty.md`. Step 0 locates the index (`cmx status --json`, then the
  `index-path.txt` sidecar, then `CONTEXTMAX_ROOT`). The answer contract, tier semantics and the
  trust footer are in the body.
- `cmx skill render` writes `<index>/skill/<name>/`; `cmx skill install --host …` copies it and
  writes the sidecar. Values are YAML-escaped; unfilled placeholders fail the render.

### 9. Tests and CI

Unit tests per module; golden files for the corpus (`symbols.jsonl`, `calls.jsonl`,
`sections.jsonl`, `references.jsonl`, `links.jsonl`) with `scripts/update_golden.py`;
determinism tests extended to every new artifact; query tests over the built corpus; HTML tests
(no external URL, `</script>` escaping, counts equal coverage); skill frontmatter validation.
The corpus grows with a MATLAB function and script pair, a LaTeX file with labels, refs, a
figure and a cite, and an HTML page with links.

## Sessions

| Session | Builds | Demo on the example |
|---|---|---|
| 1 | code contract, lexical profiles, `lexical-v1`, `resolve.py`, stage `code`, `CODEMAP.md`, tests | `cmx q callers` on a MATLAB function; scripts appear as nodes; resolution rate printed |
| 2 | document contract, four adapters, structure, text cache, references, stage `documents`, `DOCMAP.md`, tests | LaTeX outlines with labels and refs; HTML tutorial headings; unresolved cites listed |
| 3 | links, graph build and layout, query store, API and `cmx q`, tests | `cmx q search kalman`, `cmx q outline`, `cmx q section --text` with citations |
| 4 | three HTML pages, skill render and install, `INDEX.md` upgrade, `how-it-works.md`, CHANGELOG, tag `v0.1.0` | open `index.html` offline; install the skill; ask Claude Code a question and get a cited answer |

## Acceptance

1. Fixture corpus: golden files match; artifact hash identical across two runs, two locations
   and the CI matrix; every new artifact is inside the identity hash.
2. Example archive: all 149 `.m` files produce symbols (30 function files, 119 scripts);
   cross-file MATLAB calls resolve by file name with the rate printed; the 7 `.tex` files produce
   outlines, labels, cross-references, figures and unresolved external citations; the 5 HTML
   pages produce headings and links.
3. `cmx q search`, `symbol`, `callers`, `impact`, `doc`, `outline`, `section --text`, `source`
   return cited results on the archive in under a second each.
4. `viz/index.html`, `code.html`, `docs.html` open with the network disabled and show the same
   counts as `coverage.json`.
5. `cmx skill install --host claude-code-project` produces a skill that validates against the
   Agent Skills constraints, and a Claude Code session answers "how does X work" with code and
   document findings, citations and the trust footer.

## Risks and defaults

- Lexical false positives (keywords as calls, macros as definitions): keyword lists per profile,
  low confidence on every edge, and the skill treats tier C as leads. Accepted for Phase 1.
- Span ends are heuristic in tier C: recorded as `span.end_exact: false`; tree-sitter fixes it.
- Large HTML saved pages may be mostly markup: `html-v1` drops scripts and styles and keeps
  headings, paragraphs, links and tables only.
- LaTeX without a bibliography: citations are external references, never invented edges.
