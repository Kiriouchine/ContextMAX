# Phase 2 — Real code analysis

Status: done (2026-09-17, released as `v0.2.0`). Builds on Phase 1 (`v0.1.0`).

Delivered as planned, with two findings from the example archive. First, the language pack
version 1.20 downloads one platform bundle and extracts grammars from it offline afterwards, so
provisioning became "fetch the bundle once" with a ledger of requested grammars. Second, the
tree-sitter 0.26 bindings corrupt memory with the pack's grammars (crashes on different files in
identical runs); ContextMAX pins the bindings below 0.26 and, as insurance, runs tier B in a
worker process that records a crashing file as `grammar-crash`, falls back to lexical analysis
for it and continues. Tags queries without reference patterns (C, C++) keep lexical call sites
marked as such at low confidence.

## Goal

Replace lexical guesses with syntax trees wherever a grammar exists, without ever touching the
network while indexing. Python gets the reference tier A plugin with import-aware resolution;
every other language with a provisioned grammar and a tags query gets tier B; the rest stays
at tier C exactly as today. Spans become exact, resolution rates become honest per language,
and a per-file cache makes rebuilds cheap while remaining byte-identical to a full build.

On the example archive: the 149 MATLAB files move to tier B (tree-sitter `matlab` grammar) with
exact function spans; the C, C++, JavaScript and CSS files likewise; every Python project gets
tier A.

## Deliverables

### 1. Grammar provisioning (`grammars.py`, `cmx grammars`)

- `tree-sitter-language-pack` fetches each grammar on first use by default. ContextMAX keeps a
  ledger `~/.contextmax/grammars/provisioned.json` (`{name: pack version}`) and points the pack's
  cache at `~/.contextmax/grammars/pack` (`CONTEXTMAX_GRAMMAR_DIR` overrides the folder).
- `cmx grammars fetch <name>...` / `--for-project` (every language present in the current index
  that has a grammar) / `--all` (with a size warning) loads each grammar once with downloads
  enabled and records it. `cmx grammars status` lists provisioned grammars, the pack version,
  and which project languages are still tier C. `cmx doctor` shows the same.
- At index time downloads are disabled. A grammar that is not in the ledger is "not
  provisioned": the file stays tier C with the existing skip reason.

### 2. Tier B generic analyzer (`code/treesitter.py`)

- Parse with the pack's parser; run the grammar's bundled `tags.scm`; map captures:
  `@definition.function|method|class|module|interface|type|constant|macro|...` to symbols (kind
  from the capture, name from `@name`, exact `line`/`end_line` from the node, signature = first
  line of the node, doc = the adjacent comment node or `@doc` capture, parent = enclosing
  definition) and `@reference.call|class|implementation` to call sites (name and qualifier from
  the node text, caller = enclosing definition, file-level otherwise).
- Imports and regions come from the lexical profile (regexes over the file), so tier B never
  loses what tier C already found.
- A grammar without a tags query, or a parse that fails, falls back to tier C for that file with
  a note; nothing is lost silently.
- Confidence ceiling `medium`; `end_exact: true`.

### 3. Python tier A plugin (`code/plugins/python.py`, `python-ast-v1`)

- `ast` with `end_lineno`: module symbol, functions, async functions, classes, methods, nested
  definitions, lambdas skipped, module-level variables and constants (upper-case names) with a
  value preview, class fields, decorators, docstrings, parameters with annotations and defaults,
  return annotations.
- Call sites from `ast.Call` (name plus dotted qualifier), including module-level and
  class-body calls; `Class(...)` is `instantiate`.
- Imports with relative levels and aliases; each call site carries a **hint**: the imported
  module and name an alias points to, `__self__` for `self.method()`, `__class__` for
  `cls.method()`.
- Resolution (`resolve.py`): hints first (module resolved to a file, symbol by name in that file,
  evidence `import-resolved`, confidence `high`; `self` resolved inside the enclosing class,
  evidence `self`), then the existing chain. Tier A resolved edges are `high` when evidence is
  import, self, same file or qualified name, otherwise `medium`.

### 4. Dispatch and cache

- `code/run.py` picks per file: tier A plugin when available for the language, else tier B when
  the grammar is provisioned and has a tags query, else tier C.
- `cache/<sha256>.<adapter>.<version>.json` stores the `FileAnalysis`; a hit needs the same
  content hash, adapter id and adapter version. `cmx index --full` ignores the cache. A test
  proves cached and full builds are byte-identical. Cross-file resolution and everything after
  it always recompute.

### 5. Coverage, honesty and tests

- Coverage reports per-language tiers and resolution counts; `INDEX.md` and the skill summary
  state which languages are tier A, B and C.
- Golden and determinism tests run with an empty grammar folder so results never depend on what
  a machine has downloaded; tier B tests run only when the pack is installed and skip otherwise;
  CI installs the `[code]` extra and provisions `python`, `c`, `javascript` and `matlab` to
  exercise tier B on all three operating systems.

## Sessions

| Session | Builds | Demo on the example |
|---|---|---|
| 1 | grammars ledger and `cmx grammars`, tier B analyzer, dispatch | MATLAB, C and JavaScript at tier B with exact spans |
| 2 | Python tier A plugin with hints, resolver changes, confidence rules | Python resolution rate on the fixture corpus and on ContextMAX itself |
| 3 | per-file cache, `--full`, tests, docs, release 0.2.0 | rebuild of the archive in a fraction of the time, identical hashes |

## Acceptance

1. `cmx grammars fetch --for-project` on the archive provisions `matlab`, `c`, `cpp`, `javascript`,
   `css`; a following `cmx index` reports those files at tier B; indexing with the network
   disabled still works.
2. Python tier A on the fixture corpus: `main` to `helper` resolved with evidence
   `import-resolved`, nested methods with exact spans, module-level calls attributed to the
   module symbol.
3. ContextMAX indexed by itself: at least 90% of Python call sites naming project symbols resolve.
4. Cached rebuild produces the same artifact identity hash as `--full`.
5. Golden files unchanged by grammar availability; CI green on three operating systems.

## Risks and defaults

- The pack's API for disabling downloads may differ between versions: wrap it in `grammars.py`
  and pin the minimum version in `pyproject.toml`.
- Some grammars ship no `tags.scm`: they remain tier C and `cmx grammars status` says so.
- Tags queries differ in what they capture per language; the mapping table is data in
  `code/treesitter.py` and grows per language as needed.
