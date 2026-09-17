# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""query.sqlite: a derived store built from the JSONL artifacts, with FTS5 full-text search.

It is a cache, not an artifact: it is rebuilt whenever the manifest's artifact identity hash
changes, it is outside the identity hashes, and every answer it gives can be traced back to a
JSONL row. Without FTS5 the search degrades to LIKE and says so.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from contextmax.io.jsonl import iter_jsonl, read_json

STORE_SCHEMA = 4
MAX_FTS_TEXT = 200_000


def _has_fts5(con: sqlite3.Connection) -> bool:
    try:
        return bool(con.execute("select sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0])
    except sqlite3.Error:
        return False


def _artifact_hash(layout) -> str:
    if layout.manifest.is_file():
        try:
            return str(read_json(layout.manifest).get("artifact_identity_hash", ""))
        except (OSError, ValueError):
            return ""
    return ""


def ensure_store(layout, force: bool = False) -> sqlite3.Connection:
    """Open the store, rebuilding it when the index changed since it was built."""
    expected = _artifact_hash(layout)
    path = layout.query_db
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    stale = force
    try:
        row = con.execute("select value from meta where key = 'artifact_identity_hash'").fetchone()
        schema = con.execute("select value from meta where key = 'schema'").fetchone()
        if row is None or row[0] != expected or schema is None or int(schema[0]) != STORE_SCHEMA:
            stale = True
    except sqlite3.Error:
        stale = True
    if stale:
        con.close()
        if path.exists():
            path.unlink()
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        build_store(layout, con, expected)
    return con


def build_store(layout, con: sqlite3.Connection, artifact_hash: str) -> dict[str, int]:
    fts = _has_fts5(con)
    con.executescript(
        """
        create table meta(key text primary key, value text);
        create table nodes(id text primary key, kind text, family text, name text, file text, lang text,
                           tier text, role text, line integer, end_line integer, cite text, doc text,
                           parent text, payload text);
        create index nodes_kind on nodes(kind);
        create index nodes_name on nodes(name);
        create index nodes_file on nodes(file);
        create index nodes_doc on nodes(doc);
        create table edges(src text, dst text, rel text, status text, confidence text, count integer,
                           dst_name text, payload text);
        create index edges_src on edges(src);
        create index edges_dst on edges(dst);
        create index edges_rel on edges(rel);
        create index edges_dst_name on edges(dst_name);
        """
    )
    if fts:
        con.execute(
            "create virtual table fts using fts5(id unindexed, kind unindexed, name, text, tokenize='unicode61')"
        )
    else:
        con.execute("create table fts(id text, kind text, name text, text text)")
    counts = {"nodes": 0, "edges": 0, "fts": 0}
    node_rows: list[tuple] = []
    fts_rows: list[tuple] = []
    text_cache: dict[str, str] = {}

    def add_node(
        row: dict[str, Any],
        kind: str,
        family: str,
        name: str,
        file: str | None,
        lang: str | None,
        tier: str | None,
        role: str | None,
        line: int | None,
        end_line: int | None,
        cite: str,
        doc: str | None,
        parent: str | None,
    ) -> None:
        node_rows.append(
            (
                row["id"],
                kind,
                family,
                name,
                file,
                lang,
                tier,
                role,
                line,
                end_line,
                cite,
                doc,
                parent,
                json.dumps(row, sort_keys=True, ensure_ascii=False),
            )
        )

    for row in _rows(layout.index / "nodes" / "files.jsonl"):
        add_node(
            row,
            "file",
            "file",
            row["name"],
            row["file"],
            row.get("language"),
            row["tier"],
            row["role"],
            None,
            None,
            row["cite"],
            None,
            None,
        )
        fts_rows.append((row["id"], "file", row["file"], row["name"]))
    for row in _rows(layout.index / "nodes" / "symbols.jsonl"):
        add_node(
            row,
            row["kind"],
            "code",
            row["qualname"] if row["qualname"] != "(file)" else row["name"],
            row["file"],
            row.get("lang"),
            row["tier"],
            row["role"],
            row["span"]["start"],
            row["span"]["end"],
            row["cite"],
            None,
            row.get("parent"),
        )
        fts_rows.append(
            (
                row["id"],
                row["kind"],
                f"{row['name']} {row['qualname']}",
                " ".join(x for x in (row.get("signature"), row.get("doc")) if x),
            )
        )
    for row in _rows(layout.index / "nodes" / "documents.jsonl"):
        add_node(
            row,
            "document",
            "doc",
            row["title"],
            row["file"],
            None,
            row["tier"],
            row["role"],
            1,
            row.get("n_lines"),
            row["cite"],
            row["id"],
            None,
        )
        text_path = layout.index / row["text_file"]
        text = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""
        text_cache[row["id"]] = text
        fts_rows.append(
            (row["id"], "document", f"{row['title']} {row['name']}", text[:MAX_FTS_TEXT])
        )
    for row in _rows(layout.index / "nodes" / "sections.jsonl"):
        add_node(
            row,
            "section",
            "doc",
            row["title"],
            row["file"],
            None,
            None,
            None,
            row["line"],
            row["end_line"],
            row["cite"],
            row["doc"],
            row.get("parent"),
        )
        start, end = row["text_range"]
        body = text_cache.get(row["doc"], "")[start:end]
        fts_rows.append((row["id"], "section", row["title"], body[:MAX_FTS_TEXT]))
    for row in _rows(layout.index / "nodes" / "parameters.jsonl"):
        add_node(
            row,
            "parameter",
            "doc",
            row["label"],
            row["file"],
            None,
            None,
            None,
            row.get("line"),
            row.get("line"),
            row["cite"],
            row["doc"],
            row.get("section"),
        )
        fts_rows.append(
            (
                row["id"],
                "parameter",
                row["label"],
                " ".join(
                    str(x)
                    for x in (row.get("display"), row.get("unit"), row.get("formula"), row.get("context"))
                    if x
                ),
            )
        )
    for row in _rows(layout.index / "nodes" / "references.jsonl"):
        add_node(
            row,
            "reference",
            "doc",
            row["raw"],
            row["file"],
            None,
            None,
            None,
            row.get("line"),
            None,
            row["cite"],
            row["doc"],
            row.get("section"),
        )
    con.executemany("insert or replace into nodes values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", node_rows)
    counts["nodes"] = len(node_rows)
    con.executemany("insert into fts(id, kind, name, text) values (?,?,?,?)", fts_rows)
    counts["fts"] = len(fts_rows)
    edge_rows: list[tuple] = []
    for name in ("calls.jsonl", "imports.jsonl", "contains.jsonl", "links.jsonl"):
        for row in _rows(layout.index / "edges" / name):
            edge_rows.append(
                (
                    row["src"],
                    row.get("dst"),
                    row["rel"],
                    row.get("status", "resolved"),
                    row.get("confidence"),
                    row.get("count", 1),
                    row.get("dst_name"),
                    json.dumps(row, sort_keys=True, ensure_ascii=False),
                )
            )
    con.executemany("insert into edges values (?,?,?,?,?,?,?,?)", edge_rows)
    counts["edges"] = len(edge_rows)
    con.executemany(
        "insert into meta values (?, ?)",
        [
            ("schema", str(STORE_SCHEMA)),
            ("artifact_identity_hash", artifact_hash),
            ("fts5", "1" if fts else "0"),
            ("n_nodes", str(counts["nodes"])),
            ("n_edges", str(counts["edges"])),
        ],
    )
    con.commit()
    return counts


def _rows(path: Path):
    if path.is_file():
        yield from iter_jsonl(path)


def run_query_stage(ctx) -> dict[str, Any]:
    """Build the store at index time so the first query is instant."""
    manifest_hash = _artifact_hash(ctx.layout)
    path = ctx.layout.query_db
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        counts = build_store(ctx.layout, con, manifest_hash)
    finally:
        con.close()
    ctx.log(
        f"  query store: {counts['nodes']} nodes, {counts['edges']} edges, {counts['fts']} full-text rows"
    )
    return counts
