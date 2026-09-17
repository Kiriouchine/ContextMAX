# ADR-0001: Python 3.11+, cross-platform, single CLI

Status: accepted (2026-09-17)

## Context

The predecessor tool split its work between PowerShell orchestration and Python analysis. That
made it Windows-only, produced a whole class of bugs at the seam (encodings, path separators,
regex dialects, locale-dependent sorting) and meant every recipe handed to an AI agent was a
PowerShell one-liner that no macOS or Linux agent could run. ContextMAX is meant to be a product
that anyone downloads and runs on their own files.

## Decision

- One Python package, `contextmax`, requiring Python 3.11 or newer, with console scripts
  `contextmax` and `cmx`.
- No shell orchestration. Every stage, every query and every installer step is Python.
- Windows stays first-class: long paths, cloud placeholders, `py` launcher discovery and
  UTF-8-without-BOM output are tested on Windows in CI alongside macOS and Linux.
- The base install depends only on the standard library. Third-party readers and grammars are
  optional extras that degrade to a recorded skip, never to a failed build.

## Consequences

- Recipes in generated skills are CLI commands and MCP tools, valid on every OS.
- A private virtual environment is created by the bootstrap so the user's interpreter is never
  modified.
- Python 3.10 (still common) is not supported; `tomllib`, `ExceptionGroup` and modern typing are
  used freely.
