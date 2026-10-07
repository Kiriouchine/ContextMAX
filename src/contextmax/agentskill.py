"""The AI skill for one project: how to find things in the index and how to answer with citations.

One skill per project, named contextmax-<project>. It is written for Claude Code
(~/.claude/skills) and for GitHub Copilot in VS Code (~/.copilot/skills). Next to SKILL.md it
keeps project.txt (where the index is) and python.txt (the Python that has ContextMAX), so
the skill never guesses a path. Notes a person wrote in <workspace>/notes/project-notes.md travel
with it as references/project-notes.md and are read before the maps.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from contextmax import util

HOSTS = {"claude": Path.home() / ".claude" / "skills", "copilot": Path.home() / ".copilot" / "skills"}


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
    return f"""---
name: contextmax-{slug}
description: '{desc}'
---

# ContextMAX: {proj.name}

A deterministic index of this project, built by scripts with no AI in the build: every file
catalogued, every function with its exact `file:line`, who calls what, every document with its
stage and outline, the links between documents and to the code, and every named value with the
document, sheet and cell it came from. It is a fast way in, not the truth itself: cite what you
find, and open the original before you rely on it.

ContextMAX only reads. It never edits the project's files.

## Use it for
- "Where is the document about X?" / "find the requirements / test report / budget for Y"
- "Where is `foo` defined?" (exact file and line) / "who calls `foo`, what breaks if I change it?"
- "How does module X work?" / "which document specifies this code?"
- "Where does this value come from, and do the documents agree?"

## How to answer: code and documents side by side
Code is the authority for what the system **does today**; documents state **intent**. They can
disagree, and finding that out is the point. For every how/why/what answer, write three parts:

1. **What the code does**: every claim cited `code base file:line`.
2. **What the documents say**: cited by document title and section, sheet and cell for a
   workbook. If you did not open a document's text, write **Documents: not opened**.
   Naming a document is not reading it.
3. **Outcome**, exactly one: **Match** (the code does what the document says), **Only in
   documents** (written down, not found in code), **Only in code** (in the code, in no document
   opened), **Mismatch** (they differ: quote both sides).

Give parts 1 and 2 the same depth, and lead with code because it is what runs. Never mix a number
from a document into a code claim without saying which is which. A quick lookup (one location,
one path) does not need the three parts.

## First: locate the index
- `project.txt` next to this file holds the working folder: call it `$WORK`.
- `python.txt` holds the Python that has ContextMAX. Run every command below as
  `& (Get-Content python.txt) -m contextmax ...` (PowerShell), shown here as `cmx`.
- Read `$WORK\\notes\\project-notes.md` if it exists (also `references/project-notes.md` here): what the
  project's people wrote down outweighs anything inferred.
- Check freshness: `cmx status {slug} --json`.

### Status line: once per chat
End your **first** substantive answer in a chat with one line, taken from `cmx status {slug}`:

`- ContextMAX ({slug}): built <date> · <in sync | changed since the build> · confidence <High|Medium|Low> (<six words at most>)`

Lower the confidence yourself when the index is stale for what you used, when a source you needed
was not read (pending, unreadable, scanned), or when you relied on a weak link. Do not repeat the
line on later answers unless asked.

## What is in `$WORK`
- `catalogue\\all-files.csv`: every file. Columns `Folder,Priority,FirstFolder,Category,Products,DocNumbers,Name,Ext,Kilobytes,Modified,OnlineOnly,RelativePath`.
- `code\\<code base>\\`: `name-lookup.json` (name to definitions), `function-list.jsonl` (one per
  function: `callee_ids`, `caller_ids`, `external_calls`, `indirect_calls`, `ambiguous`), `call-pairs.json`,
  `module-list.json`, `code-guide.md` (read this for architecture). VHDL adds `hdl-*.json(l)` and `hdl-guide.md`.
- `documents\\`: `text-index.jsonl` and `text\\<key>.txt` (each document's text, to quote),
  `sheets\\<key>.jsonl` (every cell), `doc-list.jsonl` (documents, with stage and copies folded in),
  `doc-outlines.jsonl` (headings, shall statements, values), `params.sqlite` (every value, indexed),
  `links\\doc-to-code.jsonl`, `links\\between-docs.jsonl` (cites, quotes, shares, samepart),
  `links\\code-to-doc.json`, `document-guide.md`, `text-coverage.json` and `not-read.csv` (check these before
  saying something is not there).
- `pages\\`: the pages a person opens; `Home.html` at the top.

Code bases:

{table}

Document stages: {stages}.

## Task 1: find a document
`cmx find {slug} doc "<words or number>"`. Hits are mapped documents (their text is readable);
`other_files` are catalogue matches of any kind. Prefer the newest copy: copies and revisions are
folded into one document and listed under `copies`.

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
  (`differ_count` > 0 means they disagree); `samepart` = same part of the code, next stage (navigation,
  not traceability).

## Task 5: understand the architecture
Read `$WORK\\code\\<code base>\\code-guide.md`: modules with the calls between them, every
function with its line range, and the entry points (product code nothing calls by name).

## Task 6: read what a document says
Quote from `$WORK\\documents\\text\\<key>.txt` (key from task 1). Search all of them with
`Select-String -Path "$WORK\\documents\\text\\*.txt" -Pattern "<words>"`. Not cached (not read or
not downloaded)? Open the original at the path task 1 gives.

## Task 7: values, and where a number comes from
- By name, the main lookup: `cmx params {slug} --name "<name>"`.
- Do the documents agree? `cmx params {slug} --name "<name>" --compare`.
- By number, only when there is no name, and expect noise: `cmx params {slug} --value 12 --unit ms --named`.
- A workbook live: `cmx sheet {slug} --key <key> --trace "Sheet!B7"` walks a formula back to the
  cells and constants it uses; `--lint` finds rows whose label and value come from different rows.
The index finds the value; the live workbook confirms it. Say which one you quote.

## Task 8: links between code bases
`$WORK\\notes\\connections.json`, when it exists, holds links a call graph cannot see (between programs,
chips and devices), written by hand with the code that proves them, and shown on
`pages\\connections.html`. No such file means nobody has recorded any: say so, do not infer them.

## Ground rules
- Read-only. Never write into the project's folders.
- Prefer the index over scanning the folders.
- Absence needs proof: check `text-coverage.json`, `not-read.csv` and `not-downloaded.csv` before saying
  something does not exist.
- Never claim code compiles or that a document normatively specifies code because it names it.

## Keeping it current
`cmx build {slug}` (quick: code and links), `--documents` (also new and changed documents), `--full`
(everything, failed documents retried). The same folders give the same index: compare
`outputs_hash` in `buildinfo.json`.
"""


def install(proj, host: str = "all", python: str | None = None) -> list[str]:
    text = compose(proj, python)
    notes = proj.path("notes", "project-notes.md")
    lines = []
    for name, base in HOSTS.items():
        if host not in ("all", name):
            continue
        dest = base / f"contextmax-{proj.slug}"
        dest.mkdir(parents=True, exist_ok=True)
        util.save_text(dest / "SKILL.md", text)
        util.save_text(dest / "project.txt", str(proj.workspace))
        util.save_text(dest / "python.txt", python or sys.executable)
        if notes.exists():
            (dest / "references").mkdir(exist_ok=True)
            shutil.copyfile(notes, dest / "references" / "project-notes.md")
        lines.append(f"{name}: {dest}")
    util.save_text(proj.path("skill", "SKILL.md"), text)
    return lines
