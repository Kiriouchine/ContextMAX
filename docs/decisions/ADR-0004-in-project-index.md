# ADR-0004: The index lives in `.contextmax/` inside the project

Status: accepted (2026-09-17)

## Context

The predecessor wrote generated data to a work folder outside the project so that synced folders
would not upload gigabytes; the cost was that skills needed a sidecar to find the index and the
index was not discoverable. ContextMAX is run by a person on their own machine and must be
findable by any tool from the project itself, like `.git`.

## Decision

- Everything generated lives in `<project>/.contextmax/`. The only file meant to be committed is
  `config.json`; the generated `.gitignore` template ignores the rest.
- Commands find the project by walking up from the current directory to the nearest
  `.contextmax/`, or by `--root`, or by `CONTEXTMAX_ROOT`.
- A `.contextmax-skip` marker inside `.contextmax/` (and anywhere else the user places one)
  excludes that subtree from indexing, so the tool can never index its own output.
- `output_dir` in the config can move the generated data elsewhere for huge or synced projects;
  `.contextmax/index-path.txt` then points at it.

## Consequences

- Skills and the MCP server locate the index without configuration in the common case.
- Bulk extracted text stays inside the project tree by default; sharing an index without the text
  cache remains possible through an explicit export.
