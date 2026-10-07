# Changelog

## 0.4.0 (unreleased)

A new ContextMAX, rebuilt around four layers that each answer one question: the catalogue (where is
each file), the document map (what was intended), the code map (what the code does) and the value
database (where a value comes from). The design from 0.1 to 0.3 is kept in git history (tag v0.3.1).

- Choose any number of folders per project, each holding code, documents or both; a window with the
  Windows folder picker, a readiness check and build buttons (`ContextMAX.cmd`).
- Code maps for C (macros that stand for functions, calls through pointers counted, names defined twice
  recorded), Python (resolution through imports and `self`), MATLAB (indexing told apart from calls)
  and VHDL (entity hierarchy, design top, orphans).
- Document text cache: PDF, Word, RTF, text, Excel and CSV, old Office files through Word and Excel,
  scanned PDFs through Windows text recognition; copies folded by name and size; files in the cloud
  kept pending; incremental, with pruning after a safe write.
- Document map: stages with a recorded reason, revisions folded into one document, links to code by
  distinctive names only, "about a part of the code" kept apart from a link, headings, "shall"
  statements, links by citation (`cites`), document number (`quotes`), shared values (`shares`) and
  the same part of the code (`samepart`).
- Every named value with its source, as a list and as an indexed SQLite database; formula trace and
  row-pairing check on live workbooks.
- A strict validation gate before any page is written, by any build and by `share`.
- Pages: code in bubbles, drafting table, metro lines and zoom levels; documents as a map, a drafting
  table and a network; parameters; connections; light and dark.
- Skill for Claude Code and Copilot: answers in three parts (what the code does, what the documents
  say, and an outcome: Match, Only in documents, Only in code, Mismatch) and one status line.
- `buildinfo.json` with the input and output fingerprints kept apart, and an honest completeness verdict.
- `share` writes a portable copy for colleagues; `selfcheck` writes a verdict to send for help.
- ContextMAX's own names throughout: working folders `catalogue`, `code`, `documents`, `pages` and
  `notes`; build options `--catalogue`, `--documents` and `--full`; most counts named `<thing>_count`;
  `links/between-docs.jsonl`, `hdl-tree.json`, and the value database's tables `sources`, `places` and
  `entries`. `code-guide.md` and `hdl-guide.md` open with an overview table.

Fixed before release:

- Word read no .doc or .rtf file at all: the placeholder password was longer than the 15 characters
  Word accepts, so every Open failed. Word's text now also keeps automatic list and heading numbers
  ("3.1 Control loop"), writes a table as a row per line with tab-separated cells, and turns Word's own
  marks (manual line and page breaks, special hyphens) into plain text. Cached .doc and .rtf text is
  read once more (reader version 3).
- The RTF reader reads `\uN` characters and symbol words (dashes, bullets, quotes).
- VHDL: an `inout` port was recorded as `in` with the type `out ...`; a port without a mode lost the
  first letters of its type (`integer` became `teger`); a type's own closing parenthesis was cut off.
- When the check for Word, Excel and text recognition timed out, the hidden Word or Excel it had
  started stayed running; it is now stopped, as for every other Office step. Why the check did not
  finish is recorded, and an old .doc file left unread gives that reason instead of "this PC does not
  have Word". A scanned PDF whose text recognition failed keeps the reason (`ocr_problem`).
- `build --catalogue` wrote the pages again from the document map on disk without checking it, and
  `share` copied it unchecked; both now run the validation gate first.
- The default rules no longer carry document-type words of one particular organisation.
- `checkup` named the old installer; it now says `setup.cmd`.
- The window refused a request without its token by closing the connection before reading it, which
  Windows can turn into a reset instead of the "not allowed" answer.
- The README names the preview option of `share` as it is: `--dry-run`.
