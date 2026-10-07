# ContextMAX

**Choose your project's folders. Get a map of the code, a map of the documents, every named value with
its source, and the links between all of them. Then let your AI answer with citations.**

ContextMAX reads the folders you choose (code, documents, or both) and builds an index with scripts
alone: no AI in the build, the same folders always give the same index. It never writes into your folders.

- **Code**: every function in C, Python and MATLAB with its exact file and line, who calls it and what
  it calls, and what breaks if it changes. VHDL as its entity hierarchy. A call through a pointer is
  counted and shown, never guessed; a call to a name defined twice goes to the nearest definition, and
  the other candidates are listed with it.
- **Documents**: Word, PDF, Excel, CSV, Markdown, text, RTF, and old .doc/.xls through Microsoft Office
  when it is installed. Copies and revisions of one document fold into one, with every copy listed.
  Each document gets a lifecycle stage, its headings, its "shall" statements and its values.
- **Links**: a document that names code; a document that cites another's title or quotes its number;
  documents that state the same named value, and whether they agree; documents about the same part of
  the code.
- **Values**: every number with a unit and every spreadsheet cell, found by its name, with the sheet and
  cell it came from and the formula behind it.
- **Your AI**: a skill for Claude Code and GitHub Copilot that answers in three parts (what the code
  does, what the documents intend, and whether they agree), cites every claim, and says what it did not
  check.

## Install

1. Python 3.11 or newer from python.org.
2. Double-click **`setup.cmd`**. It creates a private environment in `%USERPROFILE%\ContextMAX\.venv`
   and leaves your own Python alone. No administrator rights.
3. Double-click **`ContextMAX.cmd`**. The window opens in your browser: name a project, add its folders
   with the folder picker, say what each holds, and press **Read documents and build**.

The `contextmax` command below lives in `%USERPROFILE%\ContextMAX\.venv\Scripts`: add that folder to
your PATH, or type the full path. To try everything on a small made-up project first: `contextmax demo`.

## The pages

Open `Home.html` in the project's working folder (`%USERPROFILE%\ContextMAX\<project>`). Everything
works offline, from the folder. A switch at the top right gives light or dark.

| Page | Views (buttons above the map) |
|---|---|
| **Code** (one per code base) | **Bubbles**: modules, then a module's functions, laid out by physics. **Drafting table**: modules as blocks holding their functions as circles, in a fixed layout. **Metro lines**: each module a coloured line, its functions the stations in call order, calls into another module as changes between lines. **Zoom levels**: code bases, then modules, then one function with its callers and callees. **Hierarchy**: VHDL entities and which one places which. |
| **Documents** | **Document map**: stages left to right, rows by how closely a document ties to the code. **Drafting table**: the same documents as pages. **Network**: linked documents and the code modules they name, laid out by physics. Each link kind can be switched on and off. |
| **Parameters** | Find a value by its name, see every document that states it, and whether they agree. Trace a cell's formula back to its constants. |
| **Connections** | Your code bases and the links a call graph cannot see (between programs, chips and devices), which you write once in `notes\connections.json`. |

Click anything for its details: file and line with an **Open in editor** link, callers and calls,
documents that name it, and the documents it links to.

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
contextmax skill install my-project         # Claude Code and Copilot
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
                    params.sqlite (every value), links\ (document and code links), document-guide.md
pages\              the pages
notes\              project-notes.md and connections.json: knowledge people write down
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
- **A gate before the pages.** A strict check recomputes and cross-checks the document map; if it
  fails, no page is written.
- **Finding aids, not the record.** Stages, links and values come from text. Open the original before
  relying on a requirement or a number.

## Optional readers

| Reader | What it adds |
|---|---|
| Microsoft Word | old `.doc` files; `.rtf` files as Word shows them (without Word, a built-in reader) |
| Microsoft Excel | formulas of old `.xls` files, and workbooks the Python reader rejects |
| Windows text recognition | scanned PDFs (add a language in Windows settings) |
| VS Code | **Open in editor** links jump to the exact line |

Without them, old `.doc` files are listed as not read with the reason (`documents\not-read.csv`), old
`.xls` files are read for their values without their formulas (their text says so), and scanned PDFs
stay without text and are counted on the home page.

Word, Excel and text recognition each run as a short PowerShell step with a time limit, and a step
that runs out of time stops any Word or Excel it started. Security software sometimes holds such a step
until it times out. When that happens to the first check, the build continues as if the readers were
missing and records why (`documents\text-info.json`, and the reason given for each `.doc` file); a
scanned PDF whose text recognition failed keeps its reason as `ocr_problem` in
`documents\text-index.jsonl`. If it keeps happening, allow ContextMAX's Python in the security software.

## License

Apache License 2.0. Made by Sev Kiriouchine. The bundled vis-network is dual licensed Apache 2.0 / MIT
(`third_party\vis-network`).
