# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Tier B: the generic tree-sitter analyzer (`treesitter-tags-v1`).

Any provisioned grammar with a bundled `tags.scm` yields definitions and call references with
exact node spans. Imports and regions still come from the lexical profile so nothing tier C
found is lost. Resolution is by name, so the confidence ceiling is `medium`.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from contextmax import grammars
from contextmax.code import lexical
from contextmax.code.base import CONTAINER_KINDS, CallSite, FileAnalysis, Symbol

ADAPTER_ID = "treesitter-tags-v1"
ADAPTER_VERSION = "1"

# Capture name -> symbol kind. Tags queries follow the tree-sitter convention
# `@definition.<kind>` / `@reference.<kind>` with the identifier under `@name`.
DEFINITION_KINDS = {
    "function": "function",
    "method": "method",
    "class": "class",
    "module": "module",
    "interface": "interface",
    "type": "type",
    "constant": "constant",
    "macro": "macro",
    "struct": "struct",
    "enum": "enum",
    "namespace": "namespace",
    "trait": "trait",
    "impl": "impl",
    "field": "field",
    "variable": "variable",
    "constructor": "constructor",
    "union": "union",
    "property": "field",
    "package": "package",
    "getter": "method",
    "setter": "method",
    "label": "label",
}
REFERENCE_KINDS = {
    "call": "call",
    "class": "instantiate",
    "implementation": "reference",
    "type": "reference",
    "module": "reference",
    "macro": "call",
    "function": "call",
}
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_queries: dict[str, Any] = {}  # compiled tags queries, kept alive with their languages
_WRAPPER_TYPES = ("definition", "declaration", "declarator", "item", "statement", "specifier")


def _definition_node(node):
    """Some tags queries capture only a declarator (C, C++); the span is the whole definition."""
    current = node
    while current.parent is not None and current.parent.parent is not None:
        parent = current.parent
        if parent.start_point.row != node.start_point.row:
            break
        if not any(w in parent.type for w in _WRAPPER_TYPES):
            break
        current = parent
    return current


def available_for(language: str | None) -> tuple[bool, str | None]:
    """(usable, grammar name) for a registry language; usable needs a provisioned grammar with tags."""
    from contextmax.registry import languages

    grammar = languages().get(language or "", {}).get("grammar")
    if not grammar:
        return False, None
    return grammars.has_tags(grammar), grammar


def analyze(key: str, text: str, language: str | None, grammar: str) -> FileAnalysis:
    from tree_sitter import Query, QueryCursor

    lang, parser = grammars.load(grammar)
    query_text = grammars.tags_query(grammar) or ""
    if grammar not in _queries:
        _queries[grammar] = Query(lang, query_text)
    query = _queries[grammar]
    has_references = "@reference" in query_text
    data = text.encode("utf-8")
    tree = parser.parse(data)
    lines = text.split("\n")
    n_lines = len(lines) - (1 if text.endswith("\n") else 0)
    result = FileAnalysis(
        key=key,
        language=language,
        tier="B",
        adapter=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        n_lines=max(n_lines, 0),
    )
    if tree.root_node.has_error:
        result.notes.append("parse errors present; some definitions may be missing")

    prof = lexical.profile_for(language)
    symbols: list[Symbol] = []
    calls: list[tuple[int, int, str, str]] = []  # (byte start, line, name text, kind)
    seen_defs: set[tuple[int, int]] = set()
    for _pattern, captures in QueryCursor(query).matches(tree.root_node):
        names = captures.get("name") or []
        name_node = names[0] if names else None
        for capture, nodes in captures.items():
            if capture == "name" or capture == "doc":
                continue
            family, _, kind_name = capture.partition(".")
            for node in nodes:
                if family == "definition":
                    kind = DEFINITION_KINDS.get(kind_name, kind_name or "definition")
                    if name_node is None:
                        continue
                    name = (
                        data[name_node.start_byte : name_node.end_byte]
                        .decode("utf-8", "replace")
                        .strip()
                    )
                    if not name or (node.start_byte, name_node.start_byte) in seen_defs:
                        continue
                    seen_defs.add((node.start_byte, name_node.start_byte))
                    node = _definition_node(node)
                    if kind == "function" and node.type in ("declaration", "field_declaration"):
                        kind = "prototype"  # a declaration without a body is not a definition
                    start_line = node.start_point.row + 1
                    end_line = node.end_point.row + 1
                    sig = lines[start_line - 1].strip() if start_line - 1 < len(lines) else name
                    doc_nodes = captures.get("doc") or []
                    doc = None
                    if doc_nodes:
                        doc = lexical._normalize_doc(
                            data[doc_nodes[0].start_byte : doc_nodes[0].end_byte]
                            .decode("utf-8", "replace")
                            .split("\n"),
                            prof.line_comments
                            + tuple(o for o, _ in prof.block_comments)
                            + tuple(c for _, c in prof.block_comments),
                        )
                    content = "\n".join(ln.rstrip() for ln in lines[start_line - 1 : end_line])
                    symbols.append(
                        Symbol(
                            name=name,
                            qualname=name,
                            kind=kind,
                            line=start_line,
                            end_line=end_line,
                            end_exact=True,
                            signature=sig[:300],
                            doc=doc,
                            visibility="private" if name.startswith("_") else "public",
                            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                            extra={
                                "node_type": node.type,
                                "start_byte": node.start_byte,
                                "end_byte": node.end_byte,
                            },
                        )
                    )
                elif family == "reference":
                    kind = REFERENCE_KINDS.get(kind_name, "reference")
                    if name_node is None:
                        continue
                    text_name = (
                        data[name_node.start_byte : name_node.end_byte]
                        .decode("utf-8", "replace")
                        .strip()
                    )
                    if text_name:
                        calls.append(
                            (name_node.start_byte, name_node.start_point.row + 1, text_name, kind)
                        )

    # Nesting from byte ranges: the innermost enclosing definition is the parent.
    symbols.sort(key=lambda s: (s.extra["start_byte"], -s.extra["end_byte"]))
    stack: list[Symbol] = []
    for sym in symbols:
        while stack and not (
            stack[-1].extra["start_byte"] < sym.extra["start_byte"]
            and sym.extra["end_byte"] <= stack[-1].extra["end_byte"]
        ):
            stack.pop()
        if stack:
            sym.parent = stack[-1].qualname
            sym.qualname = f"{stack[-1].qualname}.{sym.name}"
        if sym.kind in CONTAINER_KINDS or sym.end_line > sym.line:
            stack.append(sym)

    # Docs the tags query did not provide: the lexical profile's doc position.
    if any(s.doc is None for s in symbols):
        lex = lexical.analyze(key, text, language)
        lex_doc = {(s.line, s.name): s.doc for s in lex.symbols if s.doc}
        for sym in symbols:
            if sym.doc is None:
                sym.doc = lex_doc.get((sym.line, sym.name))
        params_by = {(s.line, s.name): (s.params, s.returns) for s in lex.symbols}
        for sym in symbols:
            if not sym.params and (sym.line, sym.name) in params_by:
                sym.params, sym.returns = params_by[(sym.line, sym.name)]
    else:
        lex = lexical.analyze(key, text, language)

    line_starts = [0]
    for ln in lines[:-1]:
        line_starts.append(line_starts[-1] + len(ln.encode("utf-8")) + 1)
    line_starts.append(len(data) + 1)

    def span_bytes(sym: Symbol) -> tuple[int, int]:
        if "start_byte" in sym.extra:
            return sym.extra["start_byte"], sym.extra["end_byte"]
        start = line_starts[min(sym.line - 1, len(line_starts) - 1)]
        end = line_starts[min(sym.end_line, len(line_starts) - 1)]
        return start, end

    def enclosing(byte: int) -> Symbol | None:
        best = None
        best_start = -1
        for sym in symbols:
            if sym.kind == "region":
                continue
            s0, e0 = span_bytes(sym)
            if s0 <= byte < e0 and s0 > best_start:
                best, best_start = sym, s0
        return best

    call_sites: list[CallSite] = []
    def_positions = {(s.line, s.name) for s in symbols}
    keywords = prof.keywords
    for byte, line, text_name, kind in calls:
        name, qualifier = lexical._split_qualified(text_name)
        if not name or name.lower() in keywords or (line, name) in def_positions:
            continue
        owner = enclosing(byte)
        col = byte - (data.rfind(b"\n", 0, byte) + 1) + 1
        call_sites.append(
            CallSite(
                caller=owner.qualname if owner else None,
                name=name,
                qualifier=qualifier,
                line=line,
                col=col,
                kind=kind,
            )
        )

    if not has_references:
        # The grammar names definitions but not references: keep the lexical call sites,
        # re-attributed to the exact symbol spans, and say so.
        result.notes.append(
            "tags query has no reference patterns; call sites from lexical patterns"
        )
        for c in lex.calls:
            byte = sum(len(ln.encode("utf-8")) + 1 for ln in lines[: c.line - 1]) + max(
                c.col - 1, 0
            )
            owner = enclosing(byte)
            call_sites.append(
                CallSite(
                    caller=owner.qualname if owner else None,
                    name=c.name,
                    qualifier=c.qualifier,
                    line=c.line,
                    col=c.col,
                    kind=c.kind,
                    source="lexical",
                )
            )
    # File-level symbol when code runs outside definitions, or nothing was defined.
    stem = key.rsplit("/", 1)[-1]
    stem = stem[: stem.rfind(".")] if "." in stem[1:] else stem
    if any(c.caller is None for c in call_sites) or not symbols:
        kind = "script" if prof.file_kind == "script" else "module"
        file_doc = next((s.doc for s in lex.symbols if s.qualname == "(file)"), None)
        content = "\n".join(ln.rstrip() for ln in lines)
        symbols.append(
            Symbol(
                name=stem,
                qualname="(file)",
                kind=kind,
                line=1,
                end_line=max(n_lines, 1),
                end_exact=True,
                signature=f"{kind} {stem}",
                doc=file_doc,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
        )
        for c in call_sites:
            if c.caller is None:
                c.caller = "(file)"
    # Definitions the tags query has no pattern for (macros, targets) still come from the profile.
    known = {(s.line, s.name) for s in symbols}
    for extra in lex.symbols:
        if extra.kind in ("macro", "target", "stage") and (extra.line, extra.name) not in known:
            symbols.append(extra)
            known.add((extra.line, extra.name))
    for region in (s for s in lex.symbols if s.kind == "region"):
        symbols.append(region)
    for sym in symbols:
        sym.extra = {"node_type": sym.extra["node_type"]} if "node_type" in sym.extra else {}
    result.symbols = sorted(symbols, key=lambda s: (s.line, s.qualname))
    result.calls = call_sites
    result.imports = lex.imports
    result.notes.extend(lex.notes)
    return result
