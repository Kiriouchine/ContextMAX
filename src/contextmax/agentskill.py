"""The AI skill for one project: how to find things in the index and how to answer with citations.

One skill per project, named contextmax-<project>. It is written for Claude Code
(~/.claude/skills) and for GitHub Copilot in VS Code (~/.copilot/skills). SKILL.md is short: it
starts the assistant with `contextmax brief`, one call that shows where a question leads, and holds
the rules for answering; the Python and the working folder are written in, so no call is spent
finding them. references/index-files.md describes every file of the index, read when a task needs
it. Next to SKILL.md it also keeps project.txt and python.txt. Notes a person wrote in
<workspace>/notes/project-notes.md travel with it as references/project-notes.md.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from contextmax import util

HOSTS = {"claude": Path.home() / ".claude" / "skills", "copilot": Path.home() / ".copilot" / "skills",
         "codex": Path.home() / ".codex" / "skills"}


def _keywords(proj) -> str:
    words = []
    for t in proj.code_targets:
        words.append(t["label"])
        mods = util.load_json(proj.code_dir / t["name"] / "module-list.json", default={}) or {}
        words += [m.rsplit("/", 1)[-1] for m in list(mods)[:20]]
    voc = proj.vocabulary
    words += [t["tag"] for t in voc.get("products", [])]
    for d in util.load_jsonl(proj.documents_dir / "doc-list.jsonl")[:15]:
        words.append(d["title"])
    seen, out = set(), []
    for w in words:
        k = w.lower()
        if k not in seen and len(w) >= 3:
            seen.add(k)
            out.append(w)
    return ", ".join(out[:40])


def compose(proj, python: str | None = None) -> str:
    python = python or sys.executable
    targets = [t for t in proj.code_targets if (proj.code_dir / t["name"] / "overview.json").exists()]
    rows = []
    for t in targets:
        s = util.load_json(proj.code_dir / t["name"] / "overview.json", default={}) or {}
        langs = ", ".join(f"{k} {v}" for k, v in (s.get("languages") or {}).items())
        vh = f", VHDL {s['vhdl']['entities_count']} entities" if s.get("vhdl") else ""
        rows.append(f"| `{t['name']}` | {t['label']} | {langs or 'none'}{vh} | {s.get('functions_count', 0)} functions |")
    table = "\n".join(["| code base | folder | languages | size |", "|---|---|---|---|"] + rows) if rows else "_No code mapped._"
    stages = ", ".join(proj.vocabulary.get("stages") or [])
    desc = (f"ContextMAX index of {proj.name}: its code (call graph, impact), its documents "
            f"(stages, requirements, links) and every named value with its source. Use when asked where something "
            f"is, how the code works, who calls a function or what breaks if it changes, which document specifies "
            f"something, or where a number comes from and whether the documents agree. Keywords: {_keywords(proj)}")
    desc = desc.replace("'", "’")[:1020]
    slug = proj.slug
    py = str(python).replace("\\", "/")
    ws = str(proj.workspace).replace("\\", "/")
    folders = "; ".join(f"`{str(f.path).replace(chr(92), '/')}` ({f.holds})" for f in proj.folders) or "none"
    return f"""---
name: contextmax-{slug}
description: '{desc}'
---

# ContextMAX: {proj.name}

A ready index of this project (its code, its documents and every named value), built by scripts with no AI.
It is the fast way in: one command shows where a question leads, with the lines to read. The files are the
truth. ContextMAX only reads; it never edits the project's files.

## Start with one command
Run it in Bash (Git Bash on Windows). In PowerShell write `& "{py}" -m contextmax ...`, and do not pipe its
output into another program: PowerShell adds a byte-order mark that breaks it.

    "{py}" -m contextmax brief {slug} "<the question, in the words the project would use>"

In a few seconds it prints:
- **Named in the question**: a function or named number the question names exactly, with its definition, its
  callers (the line of each call), how far a change reaches, its uses, and every document line that names it.
- **The part the question names** (a module such as laser_control): every named number of it (the value in
  effect, the uses) and every value its documents state, marked where the documents differ.
- **Ways in**: the places to read first, each with the line it points at, quoted, and for each family of
  constants or each value among them every file or document that sets or states it.

Its first line is the index's build date and confidence. Everything in it was read from the files and checked
at the cited line: confirm by opening a few of those lines and reading the whole function or passage there,
then search yourself only for what the brief does not cover. Rebuilding its lists by hand costs turns and
adds nothing. Most questions need the brief and a few reads.

## Going deeper (plain text; add --json for everything)
`cmx` below means `"{py}" -m contextmax`.
- `cmx find {slug} symbol|callers|impact <name>`: a function or a named number (#define, const, a
  MATLAB or Python constant, a VHDL generic): where it is defined, every use (file:line and function), who
  calls it, what a change reaches. Quote the impact's caveat: calls through pointers are not followed.
- `cmx find {slug} doc "<words>"`: documents by title, and by their text, each hit at its line.
- `cmx params {slug} --name "<name>" --compare`: every document that states a value, and whether they agree.
  With no hit it lists names that share the words.
- `cmx find {slug} code-for "<document>"`, `docs-for <name>`, `links "<document>"`: documents and code that
  name each other; links between documents.
- `cmx sheet {slug} --key <key> --trace "Sheet!B7"`: a workbook's cell traced back to its inputs, live.
- `cmx status {slug}`: whether the files changed since the build (slower: it hashes every code file).

## Where things are
- A document's text, to read and quote: `{ws}/documents/text/<key>.txt` (lines as the brief cites them). The
  original file's path is in `documents/text-index.jsonl`; `text_sha256` there is the hash of the extracted
  text, not of the file, so two files with the same text share it.
- The project's own folders: {folders}.
- Notes the project's people wrote, read before anything inferred: `{ws}/notes/project-notes.md`
  (also `references/project-notes.md` next to this file).
- Every file of the index, what each holds, and how to read links and values: `references/index-files.md`
  next to this file.

## The source is the truth
ContextMAX is the way in, not the answer. A value, a link or a passage in the index tells you **where to
look**; the document or the code says **what is true**. For every answer:
1. Find it with the brief (or a lookup below): it gives the document and the line, the sheet and cell, or the
   code file and line.
2. Open that source and read the whole passage, from the heading above to the next: the document's text at
   the cited line (`{ws}/documents/text/<key>.txt`), the workbook's rows around the cell, or the whole
   function in the code file at `file:line`.
3. Follow what the passage points to (a table, a figure, a requirement, another document, a function it
   calls) and read that too. Where the extracted text is garbled (formulas, tables, figures, a scanned
   page), open the original (its path is in `text-index.jsonl`; for a PDF, the page) and read it there.
4. Answer from what the source says, not from the index's fields. Quote the exact words with their line or
   page, and link the file, cited as ContextMAX cites (below).
5. When the source says something other than the index (a number read wrong, a name taken from the wrong
   words), the source wins: say so. Where documents disagree, quote each.

## End every answer with its confidence
`Confidence: High | Medium | Low (the reason, in a few words)`, judged on what you read, not on what the
index says:
- **High**: you opened the source and it states the answer directly; where code and documents both apply,
  they agree.
- **Medium**: you read the source, but it answers only in part or indirectly; or only one source where more
  would be expected; or the index is older than the files (`cmx status {slug}`).
- **Low**: you answered from the index without opening the source; or the sources disagree and nothing
  settles it; or the link is weak (one shared name).
- **Not found**: say plainly that the index and the sources you opened do not answer it, and list what you
  searched (names, words, files). Never fill a gap with a guess.

## How to answer: code and documents side by side
Code is the authority for what the system **does today**; documents state **intent**. They can
disagree, and finding that out is the point. For every how/why/what answer, write three parts:

1. **What the code does**: every claim cited `code base file:line`.
2. **What the documents say**: cited the way ContextMAX cites, `Document · stage · page 12, line 340 ·
   §3.1 PID step` (page for a PDF, line in the document's text, the section above it), or
   `Workbook · stage · Sheet!B7` for a cell. Every value row carries these fields (`line_no`, `page`,
   `section`, `sheet`, `cell`). If you did not open a document's text, write **Documents: not opened**.
   Naming a document is not reading it.
3. **Outcome**, exactly one: **Match** (the code does what the document says), **Only in
   documents** (written down, not found in code), **Only in code** (in the code, in no document
   opened), **Mismatch** (they differ: quote both sides).

Give parts 1 and 2 the same depth, and lead with code because it is what runs. Never mix a number
from a document into a code claim without saying which is which. A quick lookup (one location,
one path) does not need the three parts.

### Status line: once per chat
End your **first** substantive answer in a chat with one line, from the brief's first line:

`- ContextMAX ({slug}): built <date> · confidence <High|Medium|Low> (<six words at most>)`

Lower the confidence yourself when a source you needed was not read (pending, unreadable, scanned) or when you
relied on a weak link. Do not repeat the line on later answers unless asked.

## Traps
- Run ContextMAX with the Python above. `python3` on Windows can open the Microsoft Store and hang.
- Searching the project's whole folder can be slow and misleading: other tools' indexes and exports may lie in
  it. Start from the brief, then search the folders and files it names.
- Read-only: never write into the project's folders.
- Absence needs proof: before saying something is not there, check `documents/text-coverage.json` and
  `documents/not-read.csv` (documents that could not be read).
- Never claim code compiles, or that a document normatively specifies code because it names it.

Code bases:

{table}

Document stages: {stages}.

## Keeping it current
`cmx build {slug}` (quick: code and links), `--documents` (also new and changed documents), `--full`
(everything, failed documents retried). The same folders give the same index: compare
`outputs_hash` in `buildinfo.json`.
"""


def reference(proj) -> str:
    """references/index-files.md: every file of the index and how to read its links and values (the skill
    itself stays short; this is read when a task needs it)."""
    slug = proj.slug
    return f"""# The ContextMAX index of {proj.name}, file by file

`$WORK` is the working folder: `{proj.workspace}`. `cmx` is the Python in the skill with `-m contextmax`.

## What is in `$WORK`
- `catalogue\\all-files.csv`: every file. Columns `Folder,Priority,FirstFolder,Category,Products,DocNumbers,Name,Ext,Kilobytes,Modified,OnlineOnly,RelativePath`.
- `code\\<code base>\\`: `name-lookup.json` (name to definitions), `function-list.jsonl` (one per
  function: `callee_ids`, `caller_ids`, `external_calls`, `indirect_calls`, `ambiguous`), `call-pairs.json`,
  `module-list.json`, `code-guide.md` (read this for architecture), `values.jsonl` (every named number:
  #define, const, constexpr, Python and MATLAB assignments, VHDL constants and generics, with `file`,
  `line`, `unit` and where the unit came from). VHDL adds `hdl-*.json(l)` and `hdl-guide.md`.
- `documents\\`: `text-index.jsonl` and `text\\<key>.txt` (each document's text, to quote),
  `sheets\\<key>.jsonl` (every cell), `doc-list.jsonl` (documents, with stage and copies folded in),
  `doc-outlines.jsonl` (headings, shall statements, values), `params.sqlite` (every value, indexed),
  `links\\doc-to-code.jsonl`, `links\\between-docs.jsonl` (cites, quotes, shares, anchor, differs, samepart),
  `links\\code-to-doc.json`, `links\\value-to-code.jsonl` (each document value found in the code, compared in one
  unit), `value-conflicts.jsonl` (every named value documents give differently), `document-guide.md`, `text-coverage.json` and `not-read.csv` (check these before
  saying something is not there).
- `pages\\`: the pages a person opens; `Home.html` at the top.

## Task 1: find a document
`cmx find {slug} doc "<words or number>"`. First the documents whose title or path holds the words, then
those whose text says them, each at the line that says most; `other_files` are catalogue matches of any kind.
Prefer the newest copy: copies and revisions are folded into one document and listed under `copies`.

## Task 2: where is a function or entity defined
`cmx find {slug} symbol <name>`. Prefer it to a text search: names also appear in comments and
documents, the index holds only real definitions. When a name is defined more than once, the hit
lists `ambiguous` candidates: say so.

## Task 3: who calls it, what breaks if it changes
`cmx find {slug} callers <name> --depth 2` and `cmx find {slug} impact <name>`.
Product callers are the real reach; test and stub callers are the harness. **Always quote the
impact's `caveat`**: calls through pointers or objects are not followed, so a function reached
only through a pointer looks unused. For VHDL, "calls" is placement: see `hdl-guide.md`.

## Task 4: relate documents and code
- Code a document names: `cmx find {slug} code-for "<document>"`. `strong` = five or more
  distinctive code names, `some` = two to four, `one` = a single name (a lead, not a fact).
  A document marked as about a part of the code (`about_module`) names none of it: say
  "about", never "specifies".
- Documents that name a function or module: `cmx find {slug} docs-for <name>`.
- Links between documents: `cmx find {slug} links "<document>"`. `cites` = writes the other's title
  or file name; `quotes` = quotes its document number; `shares` = states the same named values
  (`differ_count` > 0 means they disagree); `anchor` = states the same value as the first document that
  states it, for a name many documents state; `differs` = most documents agree on a value and this one
  states another (`values` lists name, value here, value in most, and the cells); `samepart` = same part
  of the code, next stage (navigation, not traceability).

## Task 5: understand the architecture
Read `$WORK\\code\\<code base>\\code-guide.md`: modules with the calls between them, every
function with its line range, and the entry points (product code nothing calls by name).

## Task 6: read what a document says
Quote from `$WORK/documents/text/<key>.txt` (key from task 1). `cmx find {slug} doc "<words>"` searches
all of them in one call; grep on `$WORK/documents/text/*.txt` works too. Not cached (not read or not
downloaded)? Open the original at the path task 1 gives.

## Task 7: values, and where a number comes from
- By name, the main lookup: `cmx params {slug} --name "<name>"`.
- Do the documents agree? `cmx params {slug} --name "<name>" --compare`.
- Every value the documents give differently: `$WORK\\documents\\value-conflicts.jsonl`, one row per
  name, each value with its documents and cells; when most documents agree, `differing` lists the ones
  that do not (with no majority it is empty: the values are only different, none is the odd one out).
- By number, only when there is no name, and expect noise: `cmx params {slug} --value 12 --unit ms --named`.
- A name comes from a label (`settle time: 12 ms`), a workbook's label, or the value's own sentence
  (`a settle time of 12 ms`): `label_source` says which. A name from a sentence is a reading: open the
  document at `line_no` and read the sentence there before you rely on the name or the number. `symbol` is the symbol written with the name (`E`, `Ts`).
- A range is written with a tilde: `1~4` means from 1 to 4, never 1 minus 4. Write ranges the same way.
- Documents against the code: `$WORK\\documents\\links\\value-to-code.jsonl`, one row per document value
  and code value, with `outcome`: **match**, **mismatch**, **unit unknown** (the code or the document
  states no unit; `note` says whether the numbers agree) or **units differ** (most likely not the same
  value). `matched_by` says how the two met; `candidates_count` > 1 means several code names could be
  it. Use these as leads for the Outcome of the three-part answer, and open the code line to confirm.
- A workbook live: `cmx sheet {slug} --key <key> --trace "Sheet!B7"` walks a formula back to the
  cells and constants it uses; `--lint` finds rows whose label and value come from different rows.
The index finds the value; the live workbook confirms it. Say which one you quote.

## Task 8: links between code bases
`$WORK\\notes\\connections.json`, when it exists, holds links a call graph cannot see (between programs,
chips and devices), written by hand with the code that proves them, and shown on
`pages\\connections.html`. No such file means nobody has recorded any: say so, do not infer them.

"""


def install(proj, host: str = "all", python: str | None = None) -> list[str]:
    text = compose(proj, python)
    notes = proj.path("notes", "project-notes.md")
    lines = []
    for name, base in HOSTS.items():
        if host not in ("all", name):
            continue
        if host == "all" and name == "codex" and not base.parent.exists():
            continue                    # Codex is not on this PC: no folder made for it
        dest = base / f"contextmax-{proj.slug}"
        dest.mkdir(parents=True, exist_ok=True)
        util.save_text(dest / "SKILL.md", text)
        util.save_text(dest / "project.txt", str(proj.workspace))
        util.save_text(dest / "python.txt", python or sys.executable)
        (dest / "references").mkdir(exist_ok=True)
        util.save_text(dest / "references" / "index-files.md", reference(proj))
        if notes.exists():
            shutil.copyfile(notes, dest / "references" / "project-notes.md")
        lines.append(f"{name}: {dest}")
    util.save_text(proj.path("skill", "SKILL.md"), text)
    return lines
