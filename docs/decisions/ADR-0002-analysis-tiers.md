# ADR-0002: Four analysis tiers so every file lands in the graph

Status: accepted (2026-09-17)

## Context

The user requires a call graph "for all files"; a file missing from the graph because of its
language would produce an inaccurate context. The predecessor deliberately refused a universal
regex call graph because it would invent false edges. Both concerns are valid.

## Decision

Every file is assigned exactly one tier, recorded on the file, on every symbol and on every edge:

| Tier | Method | Confidence ceiling |
|---|---|---|
| A | dedicated language plugin: tree-sitter (or stdlib `ast`) plus language-specific import and scope resolution | high |
| B | generic tree-sitter analysis using the grammar's bundled `tags.scm` captures; same-file, then unique project-wide resolution | medium |
| C | universal lexical analyzer for text without a provisioned grammar: identifier definitions by a configurable keyword table, calls as `name(` | low |
| D | binary or unreadable: file node only, incoming path-mention edges | none |

Ambiguity is recorded as a candidate set, never collapsed to one winner. Unresolved and external
calls are stored with their names. Resolution rates are printed and written to coverage.

## Consequences

- No file is ever absent from the graph; what varies is the confidence of what is known about it.
- The generated skill explains the tiers and tells the agent to treat tier C and low-confidence
  edges as leads to verify at the cited source.
- A grammar that is not provisioned drops the file to tier C and adds a skip reason, so the user
  can see exactly which grammars to fetch.
