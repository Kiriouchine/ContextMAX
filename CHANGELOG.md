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
  scanned PDFs through text recognition; copies folded by name and size; files in the cloud
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
- `setup.cmd` installs everything itself, per user and without administrator rights: a private copy
  of the official Python (from nuget.org, checked against a pinned SHA-256; a Python already on the PC
  when there is no internet), the private environment with ContextMAX and its readers, Start menu and
  desktop shortcuts, the `contextmax` command on the PATH (in a folder of its own, so the user's own
  `python` stays first), an entry in Apps & features and `uninstall.cmd`, which keeps the projects.
  `ContextMAX.cmd` runs `setup.cmd` the first time. The window's folder picker is the modern Windows
  dialog, called directly (no tkinter), and folder names in any script work.
- **Ask your AI** on the Home page starts VS Code with Claude's chat, VS Code (Copilot), Claude Code or
  Codex in the project's working folder, with the skill installed for it (Codex too, where it is
  installed); the working folder gets `CLAUDE.md`, `AGENTS.md`, Claude Code's read access to the project's
  folders and a VS Code workspace. **A model on this PC** answers from sources ContextMAX finds in the index
  itself, through Ollama, llama.cpp's server or LM Studio, and only ever asks 127.0.0.1.
- The documents page's **Open document** and **Show in folder** work: the window opens the file, and a page
  opened from the folder uses a `contextmax-open:` link that setup.cmd registers (`--no-links` leaves it
  out). Only documents inside a ContextMAX project are opened, checked as text before anything is touched,
  so a link cannot make Windows contact another computer; a link opens only formats that carry no code.
  **Extracted text** opens in a new tab.
- The window answers only requests addressed to it on this PC (a web page that points its own name at
  127.0.0.1 is refused) and its pages cannot be framed by another site.
- A page whose data held `<!--` (an HTML comment in a Markdown document or a docstring) showed nothing;
  it shows now.
- In the code map's bubbles, a bubble that opens on a double-click carries an arrow going into a box.
- Links to a document from the code and parameters pages, and to a function from the documents page,
  select it again (the page kept only its view in the address).
- `make-offline-installer.cmd` makes a zip that installs ContextMAX on a PC without internet: the same
  Python, every package and ContextMAX itself as wheels pinned by SHA-256, RapidOCR's Cyrillic model and
  a list of the packages' licences; installed once with the network shut off before the zip is written.
- `setup.cmd` also works for user names outside the system's code page (Cyrillic, Chinese), and an update
  while ContextMAX is open moves the old environment aside instead of clearing it under the open window.
- Scanned PDFs are read page by page at 300 dpi, by Windows' text recognition and by RapidOCR, which
  setup.cmd installs: the language, the reader and the way up are chosen per page by how much of the
  text reads as words (Chinese, Japanese, Arabic and Hebrew included); a slanted scan is straightened,
  tables keep their rows and two columns are read in order. On 13 made-up test scans (English, Dutch,
  German, Russian, Chinese, a table, a slanted table, small print, a sparse page, two columns, a mixed
  document, and English and Russian pages on their side) the text matched 99.3% of characters on this
  PC, against 64.9% before. Doubtful pages are counted; a scan that could not be read is not read again
  on every build; documents an earlier version recognised are read again.
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
