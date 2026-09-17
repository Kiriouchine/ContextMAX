# How ContextMAX works

A reference to the machinery as of Phase 1. The design rationale is in [PLAN.md](PLAN.md)
and the architecture decisions in [decisions/](decisions/).

## The pipeline

`cmx index` runs these stages in order, each wrapped so a failure is recorded in
`build-state.json` and later stages still run where their inputs exist:

| Stage | Module | Writes |
|---|---|---|
| discover | `discover.py` | `nodes/files.jsonl`, `skipped.jsonl` |
| code | `code/run.py` | `nodes/symbols.jsonl`, `edges/calls.jsonl`, `edges/imports.jsonl`, `edges/contains.jsonl`, `CODEMAP.md` |
| documents | `docs/run.py` | `nodes/documents.jsonl`, `nodes/sections.jsonl`, `nodes/references.jsonl`, `text/`, `DOCMAP.md` |
| links | `link/run.py` | `edges/links.jsonl` |
| graph | `graph/build.py` | `graph/graph.json` |
| catalogs | `pipeline.py` | `coverage.json`, `INDEX.md`, `README.md` |
| viz | `viz/render.py` | `viz/index.html`, `viz/code.html`, `viz/docs.html` |
| skill | `skill/render.py` | `skill/<name>/` |
| manifest | `manifest.py` | `manifest.json` |
| query | `query/store.py` | `query.sqlite` |

Code runs before documents because document-to-code links need the symbol index; the manifest
runs after every artifact so it can hash them; the query store runs last because it records the
manifest's artifact hash to know when it is stale.

## Discovery

Every file under the configured roots is visited in sorted order. Exclusions come, in order,
from `.contextmax-skip` markers, `.gitignore` files (a standard-library matcher), built-in
folders such as `.git` and `node_modules`, and the config's `exclude` and `include` rules.
Each file is read once for its hash and line count, detected from its extension, name, shebang
or content, and assigned a **tier**: A when a dedicated analyzer or adapter can read it, B when a
provisioned tree-sitter grammar can, C when only lexical patterns apply, D when it is catalogued
only. Every demotion has a reason code in `skipped.jsonl`. Cloud placeholders are never read.

## Code analysis (tier C today)

`code/lexical.py` blanks comments and strings while preserving newlines, so every reported line
is the real line, then applies a **lexical profile** from `registry/lexical.json`: definition,
call, import and region patterns, keywords, builtins, globals, scope style and where
documentation sits. Thirty profiles cover the registry's languages; unknown text uses the
default profile. Scripts become callable file-level symbols. Array indexing in MATLAB and
similar languages is gated as "index or call".

`code/resolve.py` resolves each call site project-wide: same file, same folder, unique name,
then a file named like the callee. Several matches are recorded as `ambiguous` with all
candidates; builtins and non-project imports are `external`; the rest is `unresolved`. Bare
words (a lone identifier, a shell command) only become edges when they resolve.

## Documents (Phase 1 adapters)

`docs/adapters/` turns Markdown, plain text, HTML and LaTeX into a `DocumentTree` of ordered
blocks. `docs/structure.py` derives the outline, section ids (numbers when the document numbers
its headings, slug chains otherwise), text ranges into a rendered text cache and the table of
contents. `docs/refs.py` extracts links, figures, includes, cross-references, citations and path
mentions and resolves them against the project; the unresolved stay visible.

## Links and graph

`link/run.py` produces graded edges: reference-derived links, section-to-symbol mentions
(confidence by the number of distinct symbols a section names, inline code weighing double,
generic names suppressed) and file dependencies. `graph/layout.py` lays the graphs out with no
random source: sorted iterative depth-first search for back edges, longest-path ranks, fixed
barycentre passes, and grid-packed cluster boxes.

## Query layer

`query/store.py` builds a SQLite store with FTS5 from the JSONL; it is a cache keyed on the
manifest's artifact hash. `query/api.py` answers with dicts that carry a `cite` string.
`cmx q` prints JSON when piped and readable text on a terminal.

## Determinism

All writers sort keys and rows and emit UTF-8 without a byte order mark. The manifest records
two hashes: the baseline (semantic config, engine, source hashes) and the artifact (every
deterministic output). Timestamps, machine paths, the query store, caches, logs and the rendered
skill are outside both. CI indexes the fixture corpus on Windows, macOS and Linux and fails if
the artifact hash differs.
