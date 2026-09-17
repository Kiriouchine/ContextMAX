# ADR-0003: Stable, human-readable entity ids

Status: accepted (2026-09-17)

## Context

The predecessor identified a function as `path:line:name`. Inserting one line above a function
changed its id and every edge that mentioned it, which made diffs between builds meaningless.

## Decision

Ids are built from the relative path (forward slashes, NFC-normalized) and the qualified name,
never from the line number:

| Kind | Form |
|---|---|
| file | `file:<relpath>` |
| code symbol | `sym:<relpath>#<qualified.name>` (`~2`, `~3` ordinal suffix for duplicates in source order) |
| document | `doc:<relpath>` |
| section | `doc:<relpath>#<number-or-slug-chain>` |
| term | `term:<normalized-term>` |
| reference | `ref:<relpath>#<key-or-ordinal>` |
| parameter | `param:<relpath>#<sheet>!<cell>` |

The line span is a separate `span` field; a `content_hash` of the normalized body is stored so a
later `diff` command can recognise moves and renames.

## Consequences

- Ids survive edits elsewhere in the file and remain greppable and meaningful to a reader.
- A rename of a file or symbol produces a new id; the content hash is the bridge.
- Ids are unique project-wide, so one graph can span all languages and all documents.
