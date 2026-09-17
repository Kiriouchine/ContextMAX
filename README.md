# ContextMAX

**Deterministic, offline indexing, graphing and linking of code and documents, for people and AI agents.**

Point ContextMAX at any folder or file. It builds a searchable index of every file, a call graph
of every function across every language, an outline of every document with its references and
concepts, and the links between them. Then it generates skills for Claude Code, Claude Desktop,
VS Code Copilot, Cursor, Windsurf, Codex and any other AI system, and runs a local MCP server, so
an agent can search, navigate and **cite** the project instead of guessing.

No model is involved in building the index. The same inputs and the same engine version produce
byte-identical output on Windows, macOS and Linux. Nothing leaves your machine.

> Status: pre-alpha, under active development. See [docs/PLAN.md](docs/PLAN.md) for the design and
> roadmap and [docs/decisions/](docs/decisions/) for the architecture decisions.

## Principles

- **No model in the build.** Generation is pure code. AI reads the output; it never produces it.
- **Every file lands somewhere.** Dedicated language plugin, generic grammar, lexical parser or
  plain file node, in that order, and the tier is recorded on every symbol and edge.
- **Grade every claim.** Every edge carries a tier, a confidence and its evidence. Unresolved and
  ambiguous references are stored, never dropped.
- **Absence is never silent.** Every skipped file has a reason; every cap is announced; a partial
  build says it is partial.
- **Cite or say "not checked".** Every query result carries a citation back to the source line or
  document section.
- **Offline is a requirement.** No network while indexing, querying or viewing.

## Install (development)

```bash
py -3.14 -m venv .venv            # Windows; use python3 -m venv .venv elsewhere
.venv\Scripts\activate            # source .venv/bin/activate elsewhere
pip install -e ".[dev]"           # standard library only; add [all] for every optional reader
```

## Use

```bash
cmx init                # create .contextmax/config.json in the current project
cmx index               # build the index into .contextmax/
cmx status              # completeness, coverage by tier, what was skipped and why
cmx doctor              # environment, optional readers, grammars, detected AI hosts

cmx q search "kalman gain"          # full-text search with citations
cmx q symbol lookup_gain            # signature, doc, callers, callees, documents
cmx q impact lookup_gain            # transitive callers and callees, split by role
cmx q doc docs/guide.tex            # outline, references, symbols mentioned
cmx q section "doc:docs/guide.tex#introduction" --text
cmx q source src/app/util.py:1-12   # exact lines with a citation string
cmx q skipped                       # what was not indexed, and why

cmx viz                             # open the offline overview page
cmx skill install --host claude-code-project   # install the generated skill (see `cmx skill hosts`)
```

Everything ContextMAX generates lives in `.contextmax/`; only `config.json` is meant to be committed.
See [docs/adopting.md](docs/adopting.md) for the user guide and [docs/how-it-works.md](docs/how-it-works.md)
for the machinery.

## License

Apache License 2.0. Copyright 2026 Vsevolod Kiriouchine. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
