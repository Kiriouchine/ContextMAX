"""documents/search.sqlite: the documents' text, searchable by any process in milliseconds.

  passages   every document's text in pieces of PASSAGE_LINES lines, with its key and first and last line,
             indexed word by word (SQLite FTS5; a name with _ or - is one word: laser_control_limit1_3)
  words      in how many passages each word stands, so a rare word of a question counts more
  headings   every heading of the outline with the line of the text it stands on, indexed word by word
  info       the format version and the counts, which the gate checks

A lookup (contextmax brief, find doc, the Ask page) reads only the passages a question's words point to,
instead of reading every document's text again. The store is written in a temporary file and moved into place;
the same documents give the same bytes, so it counts towards the output fingerprint like params.sqlite.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path

from contextmax import util

FORMAT_VERSION = 2              # 2: the index only (the text stays in documents/text, read for the hits)
PASSAGE_LINES = 10
TOKENIZE = "unicode61 remove_diacritics 0 tokenchars '_-'"
_TABLES = f"""
CREATE TABLE passage_at (id INTEGER PRIMARY KEY, key TEXT NOT NULL, first INTEGER NOT NULL, last INTEGER NOT NULL);
CREATE VIRTUAL TABLE passages USING fts5(text, content = '', tokenize = "{TOKENIZE}");
CREATE VIRTUAL TABLE words USING fts5vocab(passages, row);
CREATE TABLE heading_at (id INTEGER PRIMARY KEY, key TEXT NOT NULL, line INTEGER NOT NULL, heading TEXT NOT NULL);
CREATE VIRTUAL TABLE headings USING fts5(heading, content = '', tokenize = "{TOKENIZE}");
CREATE TABLE info (name TEXT PRIMARY KEY, value TEXT);
"""
# what a lookup asks: the passages and headings that hold the words, the likeliest first
PASSAGES_SQL = ("SELECT a.key, a.first, a.last FROM passages JOIN passage_at a ON a.id = passages.rowid "
                "WHERE passages MATCH ? ORDER BY bm25(passages), a.key, a.first LIMIT ?")
HEADINGS_SQL = ("SELECT h.key, h.line, h.heading FROM headings JOIN heading_at h ON h.id = headings.rowid "
                "WHERE headings MATCH ? ORDER BY h.key, h.line")


def path_of(proj) -> Path:
    return proj.documents_dir / "search.sqlite"


def _words(s: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", s.lower()))


def heading_line(lines: list[str], heading: str, words: list[str] | None = None, start: int = 0) -> int | None:
    """The line of a document's text where a heading of its outline stands ("3.5. Fault handling  12",
    "## Fault handling", "## sheet Budget  (…)" for the headings "3.5 Fault handling", "## Fault handling",
    "sheet Budget"). `words` are the lines' words when the caller has them; the search starts at line
    start + 1 (an outline lists its headings in the order they stand) and goes round to the top."""
    want = _words(heading)
    if not want:
        return None
    words = words if words is not None else [_words(text) for text in lines]
    for n in [*range(start, len(lines)), *range(0, start)]:
        if words[n].startswith(want) and len(lines[n]) < len(heading) + 40:
            return n + 1
    return None


def chunks(lines: list[str]):
    """A document's passages: (first line, last line, text), PASSAGE_LINES lines each."""
    for start in range(0, len(lines), PASSAGE_LINES):
        text = "\n".join(lines[start:start + PASSAGE_LINES]).strip()
        if text:
            yield start + 1, min(len(lines), start + PASSAGE_LINES), text


def write(proj) -> dict:
    """The store for the documents of the document map (copies folded in: one document, one text)."""
    dm = proj.documents_dir
    docs = [d for d in util.load_jsonl(dm / "doc-list.jsonl") if d.get("cached_text")]
    heads = {o["key"]: o.get("headings") or [] for o in util.load_jsonl(dm / "doc-outlines.jsonl")}
    target = path_of(proj)
    tmp = target.with_name(target.name + ".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(str(tmp))
    passages = headings = 0
    seen: set[str] = set()                                # the same passage in two documents is searched once
    try:
        con.execute("PRAGMA page_size=4096")
        con.execute(f"PRAGMA user_version={FORMAT_VERSION}")
        con.executescript(_TABLES)
        for d in sorted(docs, key=lambda d: d["key"]):
            try:
                lines = (dm / d["cached_text"]).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for first, last, text in chunks(lines):
                if text not in seen:
                    seen.add(text)
                    passages += 1
                    con.execute("INSERT INTO passage_at (id, key, first, last) VALUES (?, ?, ?, ?)",
                                (passages, d["key"], first, last))
                    con.execute("INSERT INTO passages (rowid, text) VALUES (?, ?)", (passages, text))
            words, at = [_words(text) for text in lines], 0
            for h in heads.get(d["key"], []):
                line = heading_line(lines, h, words, at)
                if line:
                    at = line
                    headings += 1
                    con.execute("INSERT INTO heading_at (id, key, line, heading) VALUES (?, ?, ?, ?)",
                                (headings, d["key"], line, h))
                    con.execute("INSERT INTO headings (rowid, heading) VALUES (?, ?)", (headings, h))
        con.execute("INSERT INTO passages (passages) VALUES ('optimize')")
        con.execute("INSERT INTO headings (headings) VALUES ('optimize')")
        con.executemany("INSERT INTO info (name, value) VALUES (?, ?)",
                        [("documents_count", str(len(docs))), ("passages_count", str(passages)),
                         ("headings_count", str(headings)), ("passage_lines", str(PASSAGE_LINES))])
        con.commit()
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()
    for attempt in range(25):          # a lookup in the window may hold the old store for a few milliseconds
        try:
            os.replace(tmp, target)
            break
        except PermissionError:
            if attempt == 24:
                raise
            time.sleep(0.2)
    return {"documents_count": len(docs), "passages_count": passages, "headings_count": headings}


def connect(path: Path) -> sqlite3.Connection | None:
    """The store at `path`, read-only, or None when there is none (an index from before 0.4.1) or it is of another
    format. Open it for one lookup and close it: an open file cannot be replaced by the next build on Windows."""
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        if con.execute("PRAGMA user_version").fetchone()[0] != FORMAT_VERSION:
            con.close()
            return None
        return con
    except sqlite3.Error:
        return None


def open_store(proj) -> sqlite3.Connection | None:
    return connect(path_of(proj))


def check(proj) -> list[str]:
    """What the gate asks of the store: it opens, it is this format, and it holds what its info says."""
    con = open_store(proj)
    if con is None:
        return ["search.sqlite is missing or of another format"]
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            return ["search.sqlite fails its integrity check"]
        info = dict(con.execute("SELECT name, value FROM info"))
        errors = []
        if int(info.get("passages_count", -1)) != con.execute("SELECT count(*) FROM passage_at").fetchone()[0]:
            errors.append("search.sqlite holds another number of passages than it says")
        docs = sum(1 for d in util.load_jsonl(proj.documents_dir / "doc-list.jsonl") if d.get("cached_text"))
        if int(info.get("documents_count", -1)) != docs:
            errors.append("search.sqlite was written for another document map")
        return errors
    finally:
        con.close()


def match_query(words: list[str]) -> str:
    """An FTS5 query for any of the words: each word quoted (a word is a phrase of its parts, "rev.c" too)."""
    return " OR ".join('"' + w.replace('"', " ") + '"' for w in words if w.strip())
