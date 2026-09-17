# How far to trust the index

## Tiers

| Tier | Meaning | How to treat it |
|---|---|---|
| A | A dedicated analyzer read the file (a language plugin, or a document adapter) | Facts about structure; still verify quotes at the cited lines |
| B | A generic syntax grammar found definitions and references; resolution is by name | Good structure, medium-confidence edges |
| C | Lexical patterns only: definitions and calls found by regular expressions | Leads with confidence `low`; confirm with `q source` |
| D | Catalogued only: binary, unsupported, too large, unreadable, or the reader is not installed | The file exists; its content is unknown to the index |

## Edge status

- `resolved`: the target was found in the project; `evidence` says how (`same-file`,
  `unique-name`, `file-name`, `import-resolved`, `label`, `path`).
- `ambiguous`: several project symbols match; `candidates` lists them. Do not pick one silently.
- `unresolved`: the name is not defined anywhere in the project.
- `external`: a library, builtin or non-project import.

## Confidence

- Code edges: tier C edges are `low`; tier B `medium`; tier A up to `high`.
- Document-to-code mentions: `low` when a section names one symbol, `medium` for two to four
  distinct symbols, `high` for five or more; inline code spans and qualified names weigh double.
- Reference links: `high` for an exact path or label, `medium` for a basename match, none for
  unresolved.

## Things the index cannot know

- Dynamic dispatch, reflection, callbacks passed as values, MATLAB workspace variables shared
  between scripts, code generated at run time.
- Whether the code compiles or runs.
- Whether a document is current, approved or superseded.
- Anything inside a tier D file, or inside a file listed in `skipped.jsonl`.

## Wording to use

- "The index resolves X to Y (tier C, low confidence); the call is at `path:line`."
- "No mapped caller" rather than "dead code".
- "The section mentions the symbol" rather than "the document specifies the function".
- "Documentation: not checked" when you opened no document.
- "Absent from the index" plus the reason from `q skipped`, rather than "does not exist".
