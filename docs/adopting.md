# Adopting ContextMAX

This guide is for a person who wants to index their own project and let an AI assistant use
the result. Nothing here needs a network connection once the tool is installed.

## Install

Until the packaged release (Phase 8) the tool runs from a checkout:

```
git clone https://github.com/Kiriouchine/ContextMAX
cd ContextMAX
py -3.14 -m venv .venv                       # any Python 3.11 or newer
.venv\Scripts\pip install -e ".[dev]"        # standard library only; add [all] for PDF and Office readers
```

`cmx` and `contextmax` are then available inside that virtual environment. Run
`cmx doctor` to see what the machine can read.

## Grammars (optional, once)

With the `[code]` extra installed, ContextMAX can parse most languages with real syntax trees
(tier B) instead of lexical patterns (tier C). Grammars come from a bundle that must be fetched
once, with a network connection:

```
cmx grammars fetch --for-project      # the languages present in the current index
cmx grammars fetch python matlab c    # or name them
cmx grammars status                   # what is provisioned and which languages have tags queries
```

Indexing itself never downloads anything: a grammar that was not fetched leaves its files at
tier C, and `cmx status` says so. Grammars live under `~/.contextmax/grammars`
(`CONTEXTMAX_GRAMMAR_DIR` to move them).

## Index a project

```
cd <your project>
cmx init --name "My project" --description "One sentence used in the generated skill"
cmx index
cmx status
```

`init` creates `.contextmax/config.json` (the only file meant to be committed) and, in a git
repository, an ignore rule for the rest. `index` writes everything else into `.contextmax/`.
To keep the generated data elsewhere, set `"output_dir"` in the config to a folder path before
running `index`. To index a folder without writing anything into it, initialise a separate
folder and point its config at the source with `"roots": ["C:/path/to/source"]`.

## What you get

| File | What it answers |
|---|---|
| `INDEX.md` | What is in here: sizes, languages, formats, entry points, documents, what was not indexed |
| `CODEMAP.md`, `DOCMAP.md` | Every symbol per folder; every document's outline and references |
| `nodes/*.jsonl`, `edges/*.jsonl` | The data: files, symbols, documents, sections, references, calls, imports, links |
| `skipped.jsonl` | Every file not fully analysed and why |
| `coverage.json`, `manifest.json` | Counts, completeness verdict, identity hashes |
| `viz/index.html`, `code.html`, `docs.html` | Offline views; open them from disk |
| `skill/<name>/` | The rendered skill for AI assistants |

## Ask questions

```
cmx q search "kalman gain"
cmx q symbol lookup_gain
cmx q impact lookup_gain
cmx q doc docs/guide.tex
cmx q section "doc:docs/guide.tex#introduction" --text
cmx q source src/app/util.py:1-12
cmx q skipped
```

Every result carries a citation. Add `--json` for machine-readable output.

## Give it to an AI assistant

```
cmx skill hosts                                  # where each host reads skills
cmx skill install --host claude-code-project     # .claude/skills/<name>/ in the project
cmx skill install --host claude-code-user        # ~/.claude/skills/<name>/ for every project
cmx skill install --host claude-desktop          # a zip to upload under Settings > Capabilities > Skills
cmx skill install --host agents-md               # a marked block merged into AGENTS.md
```

The skill tells the assistant how to find the index, which commands answer which question, how
to cite, and how far to trust each tier. Install the same skill into several hosts; the body is
identical, only the destination differs.

## Rebuild

Run `cmx index` again after the project changes. A build reports "finished with N problem(s)"
and exits non-zero when a stage failed; the manifest then says `partial`, and the pages show a
banner. Incremental refresh arrives in a later phase; today every run is a full rebuild.

## Trust

The index is a fast way in, built without any model. Tiers say how a file was read (A dedicated
analyzer, B generic grammar, C lexical patterns, D catalogued only). Verify anything load-bearing
at the cited lines. Before concluding that something is absent, read `skipped.jsonl`.
