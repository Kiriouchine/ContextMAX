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
- C++ (`.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx` and more, and every `.h` whose own text is C++) read
  by tree-sitter's C++ parser, pinned so every PC builds the same map: each function and method with its
  namespaces and class (`motor::Controller::clamp`), its kind (function, method, constructor, destructor,
  operator) and exact lines. Calls are followed through the caller's class and its base classes, the
  namespaces and `using namespace`, qualified names, and the declared type of the object (parameters,
  local variables, fields, `this`, pointers, references, smart pointers, type aliases, `auto` from
  `new`, `make_unique` and constructors); constructors count as calls (`Motor m(2)`, `new Motor`, base
  classes and fields a constructor initialises). Overloads are told apart by their number of arguments;
  a virtual method records the methods that override it. C++ calls C functions and C calls C++
  functions with C linkage. What the text cannot settle is counted, never guessed: a method called on an
  object of unknown type (with the name of the method and how many could be meant), a call through a
  variable, a field or a pointer. A file the parser cannot fully read is named in `overview.json`.
  Documents can name C++ code with its scope (`Controller::clamp`), and C++ constants (`#define`,
  `constexpr`, `const` in capitals) are names documents can link through. On 7,000 generated C++
  files the code map takes about 14 s and is the same, byte for byte, on every build.
- Large projects build much faster, with every result unchanged: placing a document on a part of the
  code reads its text once instead of once per module, and finding cited titles looks each title up by
  its first word and length. On a made-up project of 10,060 code files and 10,000 documents the build
  went from 21 to under 5 minutes (linking documents to code 570 s to 28 s, citations 372 s to 10 s),
  and every file of the index stayed byte for byte the same.
- The Complete Atlas: a page with everything in one drawing. Every module of every code base on a wheel,
  sized by its functions, with the calls between modules; every document in its lifecycle stage, next to
  the code it names most; and every link: documents to code, and documents to documents (cited, quoted,
  shared values, values that differ, same part of the code). Modules, documents and every line can be
  clicked; a double-click opens a module's functions with the modules it calls and is called from and
  the documents that name each function. Positions come from the data alone, so the same index draws the
  same picture. On 200 modules, 9,620 documents and 164,884 links it opens in about a second.
- The build can be watched live in the ContextMAX window (off unless switched on; the text log stays).
  The build reports what it has found as it goes, and the window draws it into the Complete Atlas:
  documents as they are read, the code as it is mapped, each document moving to its stage and then
  beside the code it names, the links as they are found, the validation gate at work, and at the end
  exactly the drawing of the Complete Atlas page. On 10,060 code files and 10,000 documents the
  build took 288.5 s with it and 288.7 s without, and the index is the same either way.
- Adding, removing or changing a folder in the window builds again at once (documents read, everything
  relinked), so a link across folders is never missed; a change during a build is built right after it.
  `contextmax folders` says to build again.
- Values stated in several documents are linked completely. Two documents that state values of the same
  names are linked however many such links a document already has (before: its eight strongest); for a name
  stated by more than twelve documents, each of them links to the first document that states the same
  value (before: no link at all); and when most documents agree on a value, each document that states
  another gets a red link to the first document stating the value most give, with both values and their
  cells (with no majority, as for a unit cost every bill of materials states differently, none is marked
  as the odd one out). Every name stated with more than one value is listed in
  `documents\value-conflicts.jsonl`, the gate recomputes the list and the red
  links from the value list, and the Home page counts them. Cited titles are no longer limited to forty
  per document. On the made-up project of 10,000 documents, links between documents went from 164,884
  to 225,370 (shared values 39,622 to 61,964, and 37,052 same-value and 1,092 red links), 14,257 names
  are stated with more than one value, and the build takes a few seconds longer.
- Fixed: the window ended a build's log with "doneCount." instead of "Done.".
- The documents page's Network view opens on a large project: it laid out 9,620 documents and their
  links in about 18 s, where it had not finished after 5 minutes. Every link is still drawn as its
  own line; a large network is laid out once and then stands still, hides its lines only while it is
  dragged or zoomed, and starts from a fixed seed, so the same documents give the same picture.
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
