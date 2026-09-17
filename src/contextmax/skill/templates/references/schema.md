# Index files and fields

All JSONL files have one object per line, keys sorted, rows sorted by id. Paths use forward
slashes relative to the project root; `ext:<root>/...` marks files under an external root.

## Nodes

| File | One row per | Key fields |
|---|---|---|
| `nodes/files.jsonl` | file | `file`, `content_family`, `language`, `format`, `adapter`, `tier`, `role`, `size`, `sha256`, `lines`, `note` |
| `nodes/symbols.jsonl` | function, class, method, script, module, region, ... | `qualname`, `kind`, `file`, `span{start,end,end_exact}`, `signature`, `params`, `returns`, `doc`, `parent`, `n_callers`, `n_callees`, `cite` |
| `nodes/documents.jsonl` | document | `title`, `format`, `adapter`, `determinism`, `n_sections`, `n_words`, `toc`, `text_file` |
| `nodes/sections.jsonl` | heading-delimited section | `doc`, `title`, `depth`, `number`, `parent`, `order`, `line`, `end_line`, `text_range`, `preview`, `cite` |
| `nodes/references.jsonl` | link, citation, cross-reference, include, path mention | `ref_kind`, `raw`, `section`, `resolved`, `candidates`, `external`, `confidence`, `evidence` |

## Edges

| File | Relations |
|---|---|
| `edges/calls.jsonl` | `calls`, `instantiates`: `src`, `dst` (null when not resolved), `dst_name`, `status`, `count`, `sites[{line,col}]`, `candidates`, `evidence` |
| `edges/imports.jsonl` | `imports` between files, or to an external module name |
| `edges/contains.jsonl` | `contains`: file to symbol, parent symbol to child |
| `edges/links.jsonl` | `links`, `crossref`, `cites`, `mentions_file`, `mentions_symbol`, `depends_on` |

Every edge carries `rel`, `tier`, `confidence`, `evidence`, `status`, `adapter`.

## Other files

- `INDEX.md`, `CODEMAP.md`, `DOCMAP.md`: readable catalogs with citations.
- `text/<hash>.txt` with `text/index.jsonl`: extracted document text; section `text_range`
  offsets point into it.
- `skipped.jsonl`: every file not fully analysed, with `reason_code` and `reason`.
- `coverage.json`: counts by tier, language, format, role and reason, plus code, document and
  link statistics.
- `manifest.json`: engine version, `baseline_identity_hash` (what went in),
  `artifact_identity_hash` (what came out), `completeness`.
- `build-state.json`: the per-stage ledger of the last run.
- `graph/graph.json`: the laid-out graphs behind `viz/*.html`.
- `query.sqlite`: a derived search store; rebuilt automatically, never authoritative.
