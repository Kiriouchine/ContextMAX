# ContextMAX

**Choose your project's folders. Get a map of the code, a map of the documents, every named value with
its source, and the links between all of them. Then let your AI answer with citations.**

ContextMAX reads the folders you choose (code, documents, or both) and builds an index with scripts
alone: no AI in the build, the same folders always give the same index. It never writes into your folders.

- **Code**: every function in C, C++, Python and MATLAB with its exact file and line, who calls it and
  what it calls, and what breaks if it changes. VHDL as its entity hierarchy. A call through a pointer is
  counted and shown, never guessed; a call to a name defined twice goes to the nearest definition, and
  the other candidates are listed with it. C++ is read by a real parser (tree-sitter): namespaces,
  classes, base classes, overloads, virtual methods, constructors, and calls between C and C++; a method
  called on an object is followed through the object's declared type, and where the text does not state
  the type it is listed with its candidates instead. A `.h` file is C++ when its own text is.
- **Documents**: Word, PDF, Excel, CSV, Markdown, text, RTF, and old .doc/.xls through Microsoft Office
  when it is installed. Copies and revisions of one document fold into one, with every copy listed.
  Each document gets a lifecycle stage, its headings, its "shall" statements and its values.
- **Links**: a document that names code; a document that cites another's title or quotes its number;
  documents that state the same named value, and whether they agree; when most documents agree on a value, a
  document that states another, in red, linked to the document they follow; documents about the same part of
  the code. Every link found is kept: no document is limited to its strongest few.
- **Values**: every number with a unit and every spreadsheet cell, found by its name, with the sheet and
  cell it came from and the formula behind it.
- **Your AI**: a skill for Claude Code, GitHub Copilot and Codex that answers in three parts (what the
  code does, what the documents intend, and whether they agree), cites every claim, and says what it did
  not check. Start one from the project's Home page, or ask a model that runs on this PC (Ollama,
  llama.cpp, LM Studio): nothing leaves the PC.

## Install

Double-click **`setup.cmd`**. Nothing has to be installed first, and no administrator rights are needed.
It does everything a normal Windows program's installer does, for your user account only:

1. **Python**: a private copy of the official Python (15 MB from nuget.org, checked against a fixed
   SHA-256) in `%USERPROFILE%\ContextMAX\python`. Your own Python, if you have one, is left alone.
   If that download is not possible (a company proxy may block it), a Python 3.11 or newer that is
   already on the PC is used; the packages still need the internet, or the offline installer below.
2. **ContextMAX and its readers** (openpyxl for Excel, xlrd for old .xls, pypdfium2 for PDF, RapidOCR
   for scanned PDFs, with its Cyrillic model, tree-sitter for C++) in a private environment,
   `%USERPROFILE%\ContextMAX\.venv`.
   About 110 MB from PyPI and 8 MB from ModelScope, each model checked against a fixed SHA-256.
3. **A ContextMAX shortcut** in the Start menu and on the desktop, the **`contextmax`** command for a
   terminal (a new terminal window finds it), and an entry in **Settings > Apps** with an Uninstall
   button. Uninstalling removes the program and keeps your projects.
4. A check of what this PC can read, then the ContextMAX window opens.

Run `setup.cmd` again at any time to update. `ContextMAX.cmd` in this folder works too: the first time,
it runs `setup.cmd` for you.

In the window: name a project, add its folders with the folder picker, say what each holds, and press
**Read documents and build**. To try everything on a small made-up project first, run `contextmax demo`.

Adding a folder, removing one or changing what it holds starts a build at once: links run across folders,
so one changed folder can change links anywhere in the project. **Show the build live** (off unless you
switch it on) draws the Complete Atlas while the build runs, from the build's own results: the documents
as they are read, the code as it is mapped, each document moving to its stage, the links as they are
found, the validation gate, and at the end the same drawing as the Complete Atlas page. The text log
stays as it is. It costs the build no measurable time: on 10,060 code files and 10,000 documents
the build took 288.5 s with it and 288.7 s without.

### A PC without internet

On a PC with internet, double-click **`make-offline-installer.cmd`**. It makes
`dist\ContextMAX-<version>-offline.zip` (about 140 MB): the program, the same Python, every package and
ContextMAX itself as wheels, each pinned by its SHA-256 (so the other PC builds nothing and checks every
file), the Cyrillic model, and `wheels\THIRD-PARTY.txt` with each package's licence. Before the zip is
written, it installs the whole bundle once in a scratch folder with the network shut off, so a bundle
that would not install is never made. Copy the zip to the other PC, unzip it and double-click
`setup.cmd`: it installs from the zip alone.

It runs with a Python this PC already has: that of an installed ContextMAX, or a Python 3.11 or newer.
Only when there is none does it first install ContextMAX here (it says so).

## The pages

Open `Home.html` in the project's working folder (`%USERPROFILE%\ContextMAX\<project>`). Everything
works offline, from the folder. A switch at the top right gives light or dark.

| Page | Views (buttons above the map) |
|---|---|
| **Complete Atlas** | Everything in one drawing: every module of every code base on a wheel with the calls between them, every document in its lifecycle stage, and every link: documents to the code they name, and documents to documents (cited, quoted, shared values, values that differ, same part of the code). Click a module, a document or any line for what it connects; double-click a module for its functions, the modules it calls and is called from, and the documents that name each function. Each kind of line can be switched on and off. |
| **Code** (one per code base) | **Bubbles**: modules, then a module's functions, laid out by physics. **Drafting table**: modules as blocks holding their functions as circles, in a fixed layout. **Metro lines**: each module a coloured line, its functions the stations in call order, calls into another module as changes between lines. **Zoom levels**: code bases, then modules, then one function with its callers and callees. **Hierarchy**: VHDL entities and which one places which. |
| **Documents** | **Document map**: stages left to right, rows by how closely a document ties to the code. **Drafting table**: the same documents as pages. **Network**: linked documents and the code modules they name, laid out by physics. Each link kind can be switched on and off. |
| **Parameters** | Find a value by its name, see every document that states it, and whether they agree. Trace a cell's formula back to its constants. |
| **Connections** | Your code bases and the links a call graph cannot see (between programs, chips and devices), which you write once in `notes\connections.json`. |

Click anything for its details: file and line with an **Open in editor** link, callers and calls,
documents that name it, and the documents it links to. In **Bubbles**, a bubble with an arrow going into
a box opens: double-click it for the functions inside (or, for a function of another module, that
module). A document's details have **Open document**, **Show in folder** and **Extracted text** (in a new
tab). The pages ask the ContextMAX window to open a file; a page opened straight from the folder uses a
`contextmax-open:` link, which setup.cmd registers for your user. Either way only a file inside a
ContextMAX project (its folders or its working folder) is opened, and only a document: a program, a
script or source code is shown in its folder instead, never started. A link, which any web page can
start, opens only formats that carry no code (PDF, Word, Excel and PowerPoint without macros, text,
images); older and macro-enabled Office files open from the window, or are shown in their folder.

### Ask your AI

On the Home page, opened from the ContextMAX window, **Ask your AI** starts an assistant in the project's
working folder, with the ContextMAX skill installed for it: **VS Code with Claude** (opens the project
and Claude's chat), **VS Code** (for Copilot), **Claude Code** and **Codex** (in a terminal, when they
are installed). ContextMAX prepares the working folder for them: `CLAUDE.md` and `AGENTS.md` say what the
project is and which skill to use (in a block between two marks: what an assistant or you write there
stays), `.claude\settings.json` lets Claude Code read the project's folders (and no longer one taken out
of the project), and `<project>.code-workspace` opens them all in VS Code.

**A model on this PC** asks Ollama, llama.cpp's server or LM Studio, whichever runs. ContextMAX first finds
what the question is about in the index, by itself (functions with their code, passages of the documents,
named values), gives only that to the model, and lists those sources with links; the answer cites them
as [1], [2]. Nothing leaves the PC. Larger models answer better: on made-up questions a 26 to 31 billion
parameter model (gemma4, qwen3-coder) found that two documents disagree where an 8 billion one did not.
The first question loads the model and takes longer.

## From the command line

```
contextmax new "My project" --folder C:\work\src=code --folder D:\specs=documents
contextmax build my-project --documents     # read documents, map code, link, write pages
contextmax build my-project                 # quick refresh after a code change
contextmax build my-project --full          # everything, retrying documents that failed
contextmax open my-project
contextmax status my-project                # how fresh and complete the index is
contextmax find my-project symbol pid_step
contextmax find my-project impact pid_step
contextmax params my-project --name "settle time" --compare
contextmax sheet my-project --key Error_budget --trace "Budget!B7"
contextmax skill install my-project         # Claude Code, Copilot, and Codex where it is installed
contextmax share my-project D:\shared\maps  # a portable copy for colleagues (--dry-run to preview)
contextmax selfcheck my-project             # a verdict and a JSON file to send to whoever helps
contextmax checkup                          # what this PC can read
```

## What is in a working folder

```
project.json        your folders and the project's vocabulary (edit it to change either)
Home.html           the front door
buildinfo.json      what was mapped, how complete it is, and fingerprints to prove it
catalogue\          every file, its category, priority and document numbers (all-files.csv)
code\<base>\        function-list.jsonl, call-pairs.json, name-lookup.json, module-list.json, code-guide.md
documents\          text\ and sheets\ (what was read), doc-list.jsonl (documents), doc-outlines.jsonl,
                    params.sqlite (every value), value-conflicts.jsonl (values documents give differently),
                    links\ (document and code links), document-guide.md
pages\              the pages
notes\              project-notes.md and connections.json: knowledge people write down
CLAUDE.md, AGENTS.md, .claude\, <project>.code-workspace
                    for assistants started from Ask your AI (written by ContextMAX)
```

## The rules it keeps

- **Read-only** on your folders.
- **Deterministic.** The same folders give the same `outputs_hash` in `buildinfo.json`.
- **Nothing silently dropped.** A file that could not be read is listed with its reason
  (`documents\not-read.csv`); a file still in the cloud is listed as pending and read next time.
- **Precision before reach.** A document links to code only through names that cannot be ordinary
  words. A document about a part of the code that names none of it is marked as such, never linked.
- **A value is a name, not a number.** Values are looked up by what they measure; the number decides
  whether two documents agree.
- **A gate before the pages.** A strict check recomputes and cross-checks the document map, the values
  that differ included; if it fails, no page is written.
- **Finding aids, not the record.** Stages, links and values come from text. Open the original before
  relying on a requirement or a number.

## Optional readers

| Reader | What it adds |
|---|---|
| Microsoft Word | old `.doc` files; `.rtf` files as Word shows them (without Word, a built-in reader) |
| Microsoft Excel | formulas of old `.xls` files, and workbooks the Python reader rejects |
| Windows text recognition | scanned PDFs, in the languages added under Settings > Time & language |
| VS Code | **Open in editor** links jump to the exact line |

Without them, old `.doc` files are listed as not read with the reason (`documents\not-read.csv`), and
old `.xls` files are read for their values without their formulas (their text says so).

### Scanned PDFs

A PDF with almost no text per page is a scan. Its pages are rendered at 300 dpi and read page by page:
first by Windows' own text recognition in your first language, and where that does not read as words
(a page in another script, a page turned on the scanner), by your other Windows languages and by
RapidOCR, which setup.cmd installs: its own model reads Latin script (47 languages), Chinese and
Japanese, the Cyrillic model Russian and other Cyrillic languages. A page still unread is turned a
quarter, three quarters and half a turn; the way up with the longest flat lines of text is the page's,
and every reader tries it that way up. The text that reads most as words wins. A slanted scan is
straightened before its lines are put into rows, tables keep their rows, a two-column page is read
column by column, and each document records which reader and language read it (`ocr_readers` in
`documents\text-index.jsonl`).

Nothing is silent: a scan nothing could read keeps its reason as `ocr_problem`, and a scan with pages
whose best text still does not read as words (`ocr_doubtful_pages`) is counted; both show on the home
page. A scan that could not be read is tried again when the file changes, when the PC gains a reader
(a Windows language, RapidOCR's Cyrillic model), or with `build --full`.

RapidOCR needs the Microsoft Visual C++ 2015-2022 runtime, which almost every Windows PC has; the
check after setup says when it is missing (installing it needs an administrator).

Word, Excel and Windows' text recognition each run as a short PowerShell step with a time limit (RapidOCR
runs inside ContextMAX), and a step that runs out of time stops any Word or Excel it started. Security software sometimes holds such a step
until it times out. When that happens to the first check, the build continues as if the readers were
missing and records why (`documents\text-info.json`, and the reason given for each `.doc` file); a
scanned PDF whose text recognition failed keeps its reason as `ocr_problem` in
`documents\text-index.jsonl`. If it keeps happening, allow ContextMAX's Python in the security software.

## License

Apache License 2.0. Made by Sev Kiriouchine. The bundled vis-network is dual licensed Apache 2.0 / MIT
(`third_party\vis-network`).
