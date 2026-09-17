# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""The query API: pure functions over the store, returning JSON-ready dicts with citations.

Every answer is a pointer into the project. Rows carry `cite` (file:line-range or
document section) so a person or an agent can open the source and verify. Counts are exact;
lists may be capped by `limit` and say so with `truncated`.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contextmax.buildstate import BuildState
from contextmax.config import Config, load_config
from contextmax.fs import os_path, read_text
from contextmax.io.jsonl import iter_jsonl, read_json
from contextmax.paths import Layout, layout_for, resolve_root
from contextmax.query.store import ensure_store

CALL_RELS = ("calls", "instantiates")


class QueryError(ValueError):
    pass


@dataclass
class Index:
    root: Path
    layout: Layout
    config: Config
    con: sqlite3.Connection
    manifest: dict[str, Any]

    # --- helpers ---------------------------------------------------------------------------
    def _node(self, ident: str) -> dict[str, Any] | None:
        row = self.con.execute("select payload from nodes where id = ?", (ident,)).fetchone()
        return json.loads(row[0]) if row else None

    def _nodes(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return [json.loads(r[0]) for r in self.con.execute(sql, params).fetchall()]

    def _edges(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return [json.loads(r[0]) for r in self.con.execute(sql, params).fetchall()]

    def resolve(self, ident: str, kinds: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        """Accept an id, a symbol qualified name, a bare name, a file path or a document title."""
        node = self._node(ident)
        if node:
            return [node]
        for prefix in ("sym:", "doc:", "file:"):
            node = self._node(prefix + ident)
            if node:
                return [node]
        kind_filter = ""
        params: list[Any] = []
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            kind_filter = f" and kind in ({placeholders})"
            params.extend(kinds)
        exact = self._nodes(
            f"select payload from nodes where (name = ? or file = ?){kind_filter} order by id",
            (ident, ident, *params),
        )
        if exact:
            return exact
        like = self._nodes(
            f"select payload from nodes where (name like ? or file like ?){kind_filter} order by id limit 50",
            (f"%{ident}%", f"%{ident}%", *params),
        )
        return like

    def resolve_one(self, ident: str, kinds: tuple[str, ...] | None = None) -> dict[str, Any]:
        matches = self.resolve(ident, kinds)
        if not matches:
            raise QueryError(f"nothing matches '{ident}'")
        if len(matches) > 1:
            exact = [
                m
                for m in matches
                if m.get("qualname") == ident or m.get("name") == ident or m.get("file") == ident
            ]
            if len(exact) == 1:
                return exact[0]
            options = ", ".join(m["id"] for m in matches[:8])
            raise QueryError(f"'{ident}' is ambiguous ({len(matches)} matches): {options}")
        return matches[0]

    # --- status ----------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        cov = read_json(self.layout.coverage) if self.layout.coverage.is_file() else {}
        state = BuildState.load(self.layout.build_state) or {}
        return {
            "root": str(self.root),
            "index": str(self.layout.index),
            "project": {"slug": self.config.slug, "name": self.config.name},
            "engine_version": self.manifest.get("engine_version"),
            "generated_utc": self.manifest.get("generated_utc"),
            "baseline_identity_hash": self.manifest.get("baseline_identity_hash"),
            "artifact_identity_hash": self.manifest.get("artifact_identity_hash"),
            "completeness": self.manifest.get("completeness"),
            "coverage": {
                k: cov.get(k)
                for k in (
                    "n_files",
                    "by_tier",
                    "n_skipped",
                    "by_skip_reason",
                    "code",
                    "documents",
                    "links",
                )
            },
            "problems": state.get("problems", []),
        }

    # --- search ----------------------------------------------------------------------------
    def search(
        self, query: str, kinds: tuple[str, ...] | None = None, limit: int = 20
    ) -> dict[str, Any]:
        fts5 = self.con.execute("select value from meta where key = 'fts5'").fetchone()[0] == "1"
        hits: list[dict[str, Any]] = []
        if fts5:
            terms = " ".join(f'"{t}"' for t in query.replace('"', " ").split()) or '""'
            try:
                rows = self.con.execute(
                    "select id, kind, snippet(fts, 3, '[', ']', '…', 12) as snip, bm25(fts) as score from fts where fts match ? order by score limit ?",
                    (terms, limit * 4),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        else:
            rows = self.con.execute(
                "select id, kind, substr(text, 1, 160) as snip, 0 as score from fts where name like ? or text like ? limit ?",
                (f"%{query}%", f"%{query}%", limit * 4),
            ).fetchall()
        for row in rows:
            if kinds and row["kind"] not in kinds:
                continue
            node = self._node(row["id"])
            if node is None:
                continue
            hits.append(
                {
                    "id": node["id"],
                    "kind": node["kind"],
                    "name": node.get("title")
                    or (node.get("name") if node.get("kind") == "region" else None)
                    or (node.get("name") if node.get("qualname") == "(file)" else None)
                    or node.get("qualname")
                    or node.get("name"),
                    "file": node.get("file"),
                    "cite": node.get("cite"),
                    "tier": node.get("tier"),
                    "snippet": row["snip"],
                }
            )
            if len(hits) >= limit:
                break
        return {
            "query": query,
            "engine": "fts5" if fts5 else "like",
            "n": len(hits),
            "hits": hits,
            "truncated": len(rows) > len(hits),
        }

    # --- code ------------------------------------------------------------------------------
    def find_symbol(self, name: str, limit: int = 20) -> dict[str, Any]:
        rows = self._nodes(
            "select payload from nodes where family = 'code' and kind != 'region' and (name = ? or name like ?) order by case when name = ? then 0 else 1 end, id limit ?",
            (name, f"%{name}%", name, limit + 1),
        )
        return {
            "query": name,
            "n": min(len(rows), limit),
            "symbols": [self._sym_summary(r) for r in rows[:limit]],
            "truncated": len(rows) > limit,
        }

    def _sym_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        summary = {
            k: row.get(k)
            for k in (
                "id",
                "kind",
                "name",
                "qualname",
                "file",
                "lang",
                "tier",
                "confidence",
                "role",
                "signature",
                "doc",
                "n_callers",
                "n_callees",
                "cite",
            )
        }
        if summary.get("qualname") == "(file)":
            summary["qualname"] = row["name"]  # a script or module is known by its file name
        return summary

    def symbol(self, ident: str) -> dict[str, Any]:
        row = self.resolve_one(
            ident,
            (
                "function",
                "method",
                "class",
                "script",
                "module",
                "constructor",
                "macro",
                "struct",
                "interface",
                "enum",
                "entity",
                "type",
                "target",
                "region",
                "package",
                "architecture",
                "process",
                "component",
                "trait",
                "impl",
                "variable",
                "stage",
                "resource",
            ),
        )
        return {
            "symbol": row,
            "callers": self._neighbours(row["id"], incoming=True),
            "callees": self._neighbours(row["id"], incoming=False),
            "possible_callers": self._possible_callers(row),
            "documents": self._mentioning_sections(row["id"]),
            "contains": [self._sym_summary(c) for c in self._children(row["id"])],
        }

    def _children(self, ident: str) -> list[dict[str, Any]]:
        ids = [
            r["dst"]
            for r in self._edges(
                "select payload from edges where src = ? and rel = 'contains' order by dst",
                (ident,),
            )
        ]
        return [n for n in (self._node(i) for i in ids) if n]

    def _neighbours(self, ident: str, incoming: bool) -> list[dict[str, Any]]:
        col, other = ("dst", "src") if incoming else ("src", "dst")
        edges = self._edges(
            f"select payload from edges where {col} = ? and rel in ('calls','instantiates') and status = 'resolved' order by {other}",
            (ident,),
        )
        out = []
        for e in edges:
            node = self._node(e[other])
            if node:
                out.append(
                    {
                        **self._sym_summary(node),
                        "count": e.get("count", 1),
                        "evidence": e.get("evidence"),
                        "edge_confidence": e.get("confidence"),
                        "sites": e.get("sites", [])[:5],
                    }
                )
        return out

    def _possible_callers(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        """Ambiguous or unresolved call sites that name this symbol: leads, not edges."""
        edges = self._edges(
            "select payload from edges where rel in ('calls','instantiates') and status in ('ambiguous','unresolved') and (dst_name = ? or dst_name like ?) order by src",
            (row["name"], f"%.{row['name']}"),
        )
        out = []
        for e in edges:
            if e["status"] == "ambiguous" and row["id"] not in e.get("candidates", []):
                continue
            src = self._node(e["src"])
            if src:
                out.append(
                    {
                        "id": src["id"],
                        "qualname": src.get("qualname"),
                        "file": src.get("file"),
                        "cite": src.get("cite"),
                        "status": e["status"],
                        "count": e.get("count", 1),
                    }
                )
        return out

    def _mentioning_sections(self, ident: str) -> list[dict[str, Any]]:
        edges = self._edges(
            "select payload from edges where dst = ? and rel = 'mentions_symbol' order by src",
            (ident,),
        )
        out = []
        for e in edges:
            sec = self._node(e["src"])
            if sec:
                out.append(
                    {
                        "id": sec["id"],
                        "title": sec.get("title") or sec.get("name"),
                        "doc": sec.get("doc"),
                        "cite": sec.get("cite"),
                        "confidence": e.get("confidence"),
                        "evidence": e.get("evidence"),
                    }
                )
        return out

    def walk(self, ident: str, incoming: bool, depth: int | None) -> dict[str, Any]:
        """Breadth-first over resolved call edges with a seen-set; depth None means all hops."""
        col, other = ("dst", "src") if incoming else ("src", "dst")
        seen: dict[str, int] = {ident: 0}
        order: list[str] = []
        queue = deque([ident])
        while queue:
            node = queue.popleft()
            level = seen[node]
            if depth is not None and level >= depth:
                continue
            for e in self._edges(
                f"select payload from edges where {col} = ? and rel in ('calls','instantiates') and status = 'resolved' order by {other}",
                (node,),
            ):
                nxt = e[other]
                if nxt not in seen:
                    seen[nxt] = level + 1
                    order.append(nxt)
                    queue.append(nxt)
        rows = []
        by_role: dict[str, int] = {}
        for nid in order:
            node = self._node(nid)
            if node is None:
                continue
            by_role[node.get("role", "product")] = by_role.get(node.get("role", "product"), 0) + 1
            rows.append({**self._sym_summary(node), "hops": seen[nid]})
        direct = [r for r in rows if r["hops"] == 1]
        return {
            "symbol": ident,
            "direction": "callers" if incoming else "callees",
            "depth": depth,
            "n_direct": len(direct),
            "n_total": len(rows),
            "by_role": dict(sorted(by_role.items())),
            "nodes": rows,
        }

    def callers(self, ident: str, depth: int | None = 1) -> dict[str, Any]:
        row = self.resolve_one(ident)
        return self.walk(row["id"], incoming=True, depth=depth)

    def callees(self, ident: str, depth: int | None = 1) -> dict[str, Any]:
        row = self.resolve_one(ident)
        return self.walk(row["id"], incoming=False, depth=depth)

    def impact(self, ident: str) -> dict[str, Any]:
        row = self.resolve_one(ident)
        up = self.walk(row["id"], incoming=True, depth=None)
        down = self.walk(row["id"], incoming=False, depth=None)
        return {
            "symbol": self._sym_summary(row),
            "upstream": {k: up[k] for k in ("n_direct", "n_total", "by_role")},
            "upstream_nodes": up["nodes"],
            "downstream": {k: down[k] for k in ("n_direct", "n_total", "by_role")},
            "downstream_nodes": down["nodes"],
            "possible_callers": self._possible_callers(row),
            "documents": self._mentioning_sections(row["id"]),
            "note": "Counts are exact within the mapped project. Possible callers are call sites that name this symbol "
            "but could not be resolved; tier C edges are lexical leads, verify at the cited lines.",
        }

    # --- files -----------------------------------------------------------------------------
    def file(self, path: str) -> dict[str, Any]:
        row = self.resolve_one(path, ("file",))
        fid = row["id"]
        symbols = self._nodes(
            "select payload from nodes where family = 'code' and file = ? order by line, id",
            (row["file"],),
        )
        deps_out = self._edges(
            "select payload from edges where src = ? and rel = 'depends_on' order by dst", (fid,)
        )
        deps_in = self._edges(
            "select payload from edges where dst = ? and rel = 'depends_on' order by src", (fid,)
        )
        imports = self._edges(
            "select payload from edges where src = ? and rel = 'imports' order by dst_name", (fid,)
        )
        mentions = self._edges(
            "select payload from edges where dst = ? and rel = 'mentions_file' order by src", (fid,)
        )
        doc = self._node("doc:" + row["file"])
        return {
            "file": row,
            "document": {
                k: doc.get(k) for k in ("id", "title", "n_sections", "n_words", "n_references")
            }
            if doc
            else None,
            "symbols": [self._sym_summary(s) for s in symbols],
            "depends_on": [
                {"file": e["dst"], "evidence": e.get("evidence"), "count": e.get("count")}
                for e in deps_out
            ],
            "depended_on_by": [
                {"file": e["src"], "evidence": e.get("evidence"), "count": e.get("count")}
                for e in deps_in
            ],
            "imports": [
                {"module": e.get("dst_name"), "resolved": e.get("dst"), "status": e.get("status")}
                for e in imports
            ],
            "mentioned_by": [
                {"section": e["src"], "confidence": e.get("confidence")} for e in mentions
            ],
        }

    def deps(self, path: str, reverse: bool = False) -> dict[str, Any]:
        row = self.resolve_one(path, ("file",))
        col, other = ("dst", "src") if reverse else ("src", "dst")
        edges = self._edges(
            f"select payload from edges where {col} = ? and rel = 'depends_on' order by {other}",
            (row["id"],),
        )
        return {
            "file": row["id"],
            "direction": "dependents" if reverse else "dependencies",
            "n": len(edges),
            "files": [
                {"file": e[other], "evidence": e.get("evidence"), "count": e.get("count")}
                for e in edges
            ],
        }

    # --- documents -------------------------------------------------------------------------
    def find_document(self, query: str, limit: int = 20) -> dict[str, Any]:
        rows = self._nodes(
            "select payload from nodes where kind = 'document' and (name like ? or file like ?) order by case when name = ? then 0 else 1 end, id limit ?",
            (f"%{query}%", f"%{query}%", query, limit + 1),
        )
        return {
            "query": query,
            "n": min(len(rows), limit),
            "documents": [self._doc_summary(r) for r in rows[:limit]],
            "truncated": len(rows) > limit,
        }

    def _doc_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            k: row.get(k)
            for k in (
                "id",
                "title",
                "file",
                "format",
                "adapter",
                "determinism",
                "tier",
                "n_sections",
                "n_words",
                "n_references",
                "cite",
            )
        }

    def document(self, ident: str) -> dict[str, Any]:
        row = self.resolve_one(ident, ("document",))
        sections = self.outline(row["id"])["sections"]
        refs = self._nodes(
            "select payload from nodes where kind = 'reference' and doc = ? order by id",
            (row["id"],),
        )
        summary: dict[str, int] = {}
        for r in refs:
            state = (
                "resolved"
                if r.get("resolved")
                else ("external" if r.get("external") else "unresolved")
            )
            summary[f"{r['ref_kind']} {state}"] = summary.get(f"{r['ref_kind']} {state}", 0) + 1
        mentions = self._edges(
            "select payload from edges where rel = 'mentions_symbol' and status = 'resolved' and src in (select id from nodes where doc = ? and kind = 'section') order by dst",
            (row["id"],),
        )
        return {
            "document": row,
            "outline": sections,
            "references_summary": dict(sorted(summary.items())),
            "n_references": len(refs),
            "symbols_mentioned": sorted({e["dst"] for e in mentions}),
        }

    def outline(self, ident: str) -> dict[str, Any]:
        row = self.resolve_one(ident, ("document",))
        sections = self._nodes(
            "select payload from nodes where kind = 'section' and doc = ? order by json_extract(payload, '$.order')",
            (row["id"],),
        )
        return {
            "document": row["id"],
            "title": row.get("title"),
            "n_sections": len(sections),
            "sections": [
                {
                    k: s.get(k)
                    for k in (
                        "id",
                        "title",
                        "depth",
                        "number",
                        "parent",
                        "order",
                        "line",
                        "end_line",
                        "n_words",
                        "preview",
                        "cite",
                    )
                }
                for s in sections
            ],
        }

    def section(self, ident: str, with_text: bool = False) -> dict[str, Any]:
        row = self.resolve_one(ident, ("section", "document"))
        result: dict[str, Any] = {"section": row}
        if with_text:
            doc = row if row["kind"] == "document" else self._node(row["doc"])
            text_path = self.layout.index / doc["text_file"] if doc else None
            text = (
                text_path.read_text(encoding="utf-8") if text_path and text_path.is_file() else ""
            )
            if row["kind"] == "section":
                start, end = row["text_range"]
                text = text[start:end]
            result["text"] = text
        return result

    def references(self, ident: str) -> dict[str, Any]:
        row = self.resolve_one(ident, ("document",))
        refs = self._nodes(
            "select payload from nodes where kind = 'reference' and doc = ? order by id",
            (row["id"],),
        )
        return {"document": row["id"], "n": len(refs), "references": refs}

    # --- relations -------------------------------------------------------------------------
    def related(self, ident: str) -> dict[str, Any]:
        row = self.resolve_one(ident)
        out = self._edges("select payload from edges where src = ? order by rel, dst", (row["id"],))
        inc = self._edges("select payload from edges where dst = ? order by rel, src", (row["id"],))
        groups: dict[str, list[dict[str, Any]]] = {}
        for direction, edges in (("out", out), ("in", inc)):
            for e in edges:
                other = e["dst"] if direction == "out" else e["src"]
                node = self._node(other) if other else None
                groups.setdefault(f"{e['rel']}:{direction}", []).append(
                    {
                        "id": other,
                        "name": (node or {}).get("title")
                        or (node or {}).get("qualname")
                        or (node or {}).get("name")
                        or e.get("dst_name"),
                        "cite": (node or {}).get("cite"),
                        "status": e.get("status"),
                        "confidence": e.get("confidence"),
                        "evidence": e.get("evidence"),
                        "count": e.get("count"),
                    }
                )
        return {
            "node": {"id": row["id"], "kind": row["kind"], "cite": row.get("cite")},
            "relations": dict(sorted(groups.items())),
        }

    def explain(self, src: str, dst: str) -> dict[str, Any]:
        a = self.resolve_one(src)
        b = self.resolve_one(dst)
        edges = self._edges(
            "select payload from edges where (src = ? and dst = ?) or (src = ? and dst = ?) order by rel",
            (a["id"], b["id"], b["id"], a["id"]),
        )
        return {"src": a["id"], "dst": b["id"], "n": len(edges), "edges": edges}

    # --- catalogue -------------------------------------------------------------------------
    def skipped(self, reason: str | None = None, limit: int = 200) -> dict[str, Any]:
        rows = list(iter_jsonl(self.layout.skipped)) if self.layout.skipped.is_file() else []
        if reason:
            rows = [r for r in rows if reason in r["reason_code"] or reason in r["reason"]]
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["reason_code"]] = counts.get(r["reason_code"], 0) + 1
        return {
            "n": len(rows),
            "by_reason": dict(sorted(counts.items())),
            "rows": rows[:limit],
            "truncated": len(rows) > limit,
        }

    def source(
        self, locator: str, start: int | None = None, end: int | None = None, context: int = 0
    ) -> dict[str, Any]:
        """Exact lines from a file, by symbol id or `path[:start[-end]]`."""
        path_part = locator
        if ":" in locator and not locator.startswith(("sym:", "doc:", "file:")):
            path_part, _, span = locator.rpartition(":")
            if span and span[0].isdigit():
                if "-" in span:
                    a, b = span.split("-", 1)
                    start, end = int(a), int(b)
                else:
                    start = end = int(span)
            else:
                path_part = locator
        node = self._node(locator)
        if node is None and start is None:
            # A bare name: the symbol of that name, when there is exactly one.
            by_name = [
                n
                for n in self.resolve(locator)
                if n.get("family") == "code" and n.get("kind") != "region"
            ]
            exact = [n for n in by_name if n.get("qualname") == locator or n.get("name") == locator]
            if len(exact) == 1:
                node = exact[0]
            elif len(exact) > 1:
                options = ", ".join(n["id"] for n in exact[:8])
                raise QueryError(f"'{locator}' names {len(exact)} symbols; use an id: {options}")
        if node and node.get("family") == "code":
            path_part = node["file"]
            start = start or node["span"]["start"]
            end = end or node["span"]["end"]
        file_row = self.resolve_one(path_part, ("file",))
        key = file_row["file"]
        real = self._real_path(key)
        text, _ = read_text(Path(os_path(real)))
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()  # a trailing newline is not an extra line
        first = max(1, (start or 1) - context)
        last = min(len(lines), (end or len(lines)) + context)
        excerpt = lines[first - 1 : last]
        return {
            "file": key,
            "start": first,
            "end": last,
            "n_lines_in_file": len(lines),
            "cite": f"{key}:{first}-{last}" if first != last else f"{key}:{first}",
            "lines": [{"n": first + i, "text": line} for i, line in enumerate(excerpt)],
        }

    def _real_path(self, key: str) -> Path:
        if key.startswith("ext:"):
            from contextmax.discover import resolve_roots

            prefix, _, rest = key.partition("/")
            for r in resolve_roots(self.root, self.config):
                if r.prefix == prefix:
                    return r.path / rest
        return self.root / key


def open_index(root: str | None = None) -> Index:
    project_root = resolve_root(root)
    layout0 = layout_for(project_root, None)
    config = load_config(layout0.config)
    layout = layout_for(project_root, config.output_dir)
    if not layout.manifest.is_file():
        raise QueryError("no index built yet; run `contextmax index` first")
    manifest = read_json(layout.manifest)
    con = ensure_store(layout)
    return Index(root=project_root, layout=layout, config=config, con=con, manifest=manifest)
