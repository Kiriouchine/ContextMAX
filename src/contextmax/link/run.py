# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Build `edges/links.jsonl` from the node files written by the code and document stages.

Edge kinds produced here:
- `links`, `crossref`, `mentions_file` from resolved references;
- `mentions_symbol` from section text intersected with the symbol index, graded by the number
  of distinct symbols a section names, with inline code and qualified names weighing double;
- `depends_on` between files, derived from resolved imports and cross-file calls.

Generic names are suppressed: a symbol name shorter than the configured minimum, a stopword,
or a name mentioned by more than `max_owners` sections never becomes an edge.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from contextmax.io.jsonl import read_jsonl, write_jsonl
from contextmax.model.edges import edge_row

ADAPTER = "link-v1"
TOKEN = re.compile(r"`[^`\n]+`|[A-Za-z_][\w.]*")
STOPWORDS = frozenset(
    [
        "main",
        "test",
        "tests",
        "data",
        "value",
        "values",
        "index",
        "print",
        "table",
        "figure",
        "file",
        "files",
        "name",
        "names",
        "type",
        "time",
        "size",
        "start",
        "end",
        "run",
        "load",
        "save",
        "plot",
        "read",
        "write",
        "update",
        "init",
        "setup",
        "config",
        "default",
        "result",
        "results",
        "output",
        "input",
        "error",
        "check",
        "get",
        "set",
        "list",
        "item",
        "items",
        "node",
        "nodes",
        "edge",
        "edges",
        "text",
        "line",
        "lines",
        "count",
        "total",
        "sum",
        "step",
        "steps",
        "state",
        "states",
        "model",
        "models",
        "class",
        "object",
        "function",
        "functions",
        "method",
        "methods",
        "module",
        "modules",
        "script",
        "scripts",
        "version",
        "number",
        "numbers",
        "string",
        "strings",
        "array",
        "arrays",
        "vector",
        "matrix",
        "parameter",
        "parameters",
        "option",
        "options",
        "flag",
        "flags",
        "path",
        "paths",
        "user",
        "users",
        "log",
        "logs",
        "message",
        "messages",
        "event",
        "events",
        "code",
        "source",
        "sources",
        "target",
        "targets",
        "info",
        "status",
        "process",
        "processes",
        "system",
        "systems",
        "service",
        "services",
        "block",
        "blocks",
        "section",
        "sections",
        "page",
        "pages",
        "title",
        "format",
        "formats",
        "key",
        "keys",
        "map",
        "maps",
        "cell",
        "cells",
        "sheet",
        "sheets",
        "row",
        "rows",
        "column",
        "columns",
        "filter",
        "signal",
        "control",
        "controller",
        "observer",
        "example",
        "examples",
        "note",
        "notes",
        "report",
        "reports",
    ]
)


def _load(layout, name: str) -> list[dict[str, Any]]:
    path = layout.index / name
    return read_jsonl(path) if path.is_file() else []


def run_links_stage(ctx) -> dict[str, Any]:
    layout = ctx.layout
    config = ctx.config.data["documents"]
    min_len = int(config.get("min_symbol_length", 4))
    max_owners = int(config.get("max_owners", 40))
    stopwords = STOPWORDS | {w.lower() for w in config.get("stopwords_extra", [])}

    symbols = _load(layout, "nodes/symbols.jsonl")
    sections = _load(layout, "nodes/sections.jsonl")
    documents = _load(layout, "nodes/documents.jsonl")
    references = _load(layout, "nodes/references.jsonl")
    calls = _load(layout, "edges/calls.jsonl")
    imports = _load(layout, "edges/imports.jsonl")

    rows: list[dict[str, Any]] = []

    # 1. Reference-derived edges.
    for ref in references:
        if not ref.get("resolved"):
            continue
        src = ref.get("section") or ref["doc"]
        kind = ref["ref_kind"]
        rel = {
            "link": "links",
            "figure": "links",
            "include": "links",
            "crossref": "crossref",
            "footnote": None,
            "path": "mentions_file",
            "url": None,
            "citation": "cites",
        }.get(kind)
        if rel is None:
            continue
        rows.append(
            edge_row(
                src=src,
                dst=ref["resolved"],
                rel=rel,
                tier="A",
                confidence=ref.get("confidence") or "medium",
                evidence=f"reference:{ref.get('evidence', kind)}",
                adapter=ADAPTER,
                kind=kind,
                sites=[{"line": ref.get("line") or 0, "col": 1}],
            )
        )

    # 2. Section text -> symbols.
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_qual: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sym in symbols:
        if sym["kind"] == "region" or sym["qualname"] == "(file)":
            continue
        if len(sym["name"]) < min_len or sym["name"].lower() in stopwords:
            continue
        by_name[sym["name"]].append(sym)
        if "." in sym["qualname"]:
            by_qual[sym["qualname"]].append(sym)
    text_cache: dict[str, str] = {}
    for doc in documents:
        path = layout.index / doc["text_file"]
        if path.is_file():
            text_cache[doc["id"]] = path.read_text(encoding="utf-8")
    # First pass: count owners per name to suppress generic ones.
    owners: dict[str, set[str]] = defaultdict(set)
    section_tokens: dict[str, dict[str, int]] = {}
    for section in sections:
        text = text_cache.get(section["doc"], "")
        start, end = section["text_range"]
        body = text[start:end]
        weights: dict[str, int] = defaultdict(int)
        for m in TOKEN.finditer(body):
            token = m.group(0)
            weight = 1
            if token.startswith("`"):
                inner = token.strip("`").strip()
                inner = inner.split("(")[0].strip()
                if not inner or not re.fullmatch(r"[A-Za-z_][\w.]*", inner):
                    continue
                token = inner
                weight = 2
            if token in by_qual:
                weights[token] += weight * 2
            elif token in by_name:
                weights[token] += weight
            elif "." in token and token.split(".", 1)[0] in by_name:
                weights[token.split(".", 1)[0]] += weight  # gain_sched.m names gain_sched
        section_tokens[section["id"]] = dict(weights)
        for name in weights:
            owners[name].add(section["id"])
    generic = {name for name, secs in owners.items() if len(secs) > max_owners}
    n_generic_suppressed = len(generic)
    for section in sections:
        weights = section_tokens.get(section["id"], {})
        names = [n for n in weights if n not in generic]
        distinct = len(names)
        if not distinct:
            continue
        confidence = "high" if distinct >= 5 else ("medium" if distinct >= 2 else "low")
        for name in sorted(names):
            cands = by_qual.get(name) or by_name.get(name) or []
            weight = weights[name]
            if len(cands) == 1:
                rows.append(
                    edge_row(
                        src=section["id"],
                        dst=cands[0]["id"],
                        rel="mentions_symbol",
                        tier="A",
                        confidence=confidence,
                        evidence=f"text:{distinct}-distinct"
                        + (":code-span" if weight >= 2 else ""),
                        adapter=ADAPTER,
                        count=weight,
                        dst_name=name,
                    )
                )
            else:
                rows.append(
                    edge_row(
                        src=section["id"],
                        dst=None,
                        rel="mentions_symbol",
                        tier="A",
                        confidence="low",
                        evidence="text:ambiguous-name",
                        adapter=ADAPTER,
                        status="ambiguous",
                        count=weight,
                        dst_name=name,
                        candidates=[c["id"] for c in cands][:20],
                    )
                )

    # 3. File dependencies from imports and cross-file calls.
    dep_counts: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for imp in imports:
        if imp["status"] == "resolved" and imp["dst"]:
            dep_counts[(imp["src"], imp["dst"])]["imports"] += imp.get("count", 1)
    file_of_symbol = {s["id"]: f"file:{s['file']}" for s in symbols}
    for call in calls:
        if call["status"] != "resolved" or not call["dst"]:
            continue
        src_file = file_of_symbol.get(call["src"])
        dst_file = file_of_symbol.get(call["dst"])
        if src_file and dst_file and src_file != dst_file:
            dep_counts[(src_file, dst_file)]["calls"] += call.get("count", 1)
    for (src, dst), kinds in sorted(dep_counts.items()):
        evidence = "+".join(f"{k}:{v}" for k, v in sorted(kinds.items()))
        rows.append(
            edge_row(
                src=src,
                dst=dst,
                rel="depends_on",
                tier="C",
                confidence="medium" if "imports" in kinds else "low",
                evidence=evidence,
                adapter=ADAPTER,
                count=sum(kinds.values()),
            )
        )

    ctx.artifacts["edges/links.jsonl"] = write_jsonl(
        layout.edges / "links.jsonl", rows, key=_edge_key
    )
    by_rel: dict[str, int] = defaultdict(int)
    by_conf: dict[str, int] = defaultdict(int)
    for row in rows:
        by_rel[row["rel"]] += 1
        by_conf[row["confidence"] or "none"] += 1
    ctx.log(
        f"  {len(rows)} link edges: "
        + ", ".join(f"{k}={v}" for k, v in sorted(by_rel.items()))
        + f"; {n_generic_suppressed} generic names suppressed"
    )
    return {
        "n_edges": len(rows),
        "by_rel": dict(sorted(by_rel.items())),
        "by_confidence": dict(sorted(by_conf.items())),
        "n_generic_suppressed": n_generic_suppressed,
    }


def _edge_key(row: dict[str, Any]) -> tuple:
    return (row["src"], row["rel"], row["dst"] or "", row.get("dst_name") or "")
