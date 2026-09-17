# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Tier C: the universal lexical analyzer (`lexical-v1`).

It knows nothing about grammar. It blanks comments and strings while keeping every newline so
reported lines are exact, then applies a language profile from `registry/lexical.json`: how
definitions, calls, imports and regions look, which words are keywords, how scopes end and where
documentation sits. Everything it emits carries confidence "low"; it is a way in, not a proof.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
from dataclasses import dataclass
from functools import cache, lru_cache
from importlib import resources
from typing import Any

from contextmax.code.base import CONTAINER_KINDS, CallSite, FileAnalysis, Import, Symbol

ADAPTER_ID = "lexical-v1"
ADAPTER_VERSION = "1"
MAX_DOC_CHARS = 500
MAX_LINE_CHARS = 20_000  # a minified line is truncated before regexes see it (ReDoS guard)

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass(frozen=True)
class DefRule:
    kind: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class ImportRule:
    kind: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class Profile:
    id: str
    line_comments: tuple[str, ...]
    block_comments: tuple[tuple[str, str], ...]
    block_comment_alone: bool
    strings: tuple[str, ...]
    string_escape: str | None
    matlab_transpose: bool
    definitions: tuple[DefRule, ...]
    calls: re.Pattern[str] | None
    bare_calls: re.Pattern[str] | None
    call_kind: str
    keywords: frozenset[str]
    builtins: frozenset[str]
    globals_: frozenset[str]
    imports: tuple[ImportRule, ...]
    regions: tuple[re.Pattern[str], ...]
    scope: str
    doc_position: str
    file_kind: str
    index_syntax: bool


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    with (
        resources.files("contextmax.registry")
        .joinpath("lexical.json")
        .open("r", encoding="utf-8") as h
    ):
        return json.load(h)


@cache
def profile(profile_id: str) -> Profile:
    data = _raw()["profiles"][profile_id]
    flags = re.MULTILINE | (re.IGNORECASE if data.get("case_insensitive") else 0)
    return Profile(
        id=profile_id,
        line_comments=tuple(data.get("line_comments", [])),
        block_comments=tuple((a, b) for a, b in data.get("block_comments", [])),
        block_comment_alone=bool(data.get("block_comment_alone", False)),
        strings=tuple(data.get("strings", [])),
        string_escape=data.get("string_escape"),
        matlab_transpose=bool(data.get("matlab_transpose", False)),
        definitions=tuple(
            DefRule(d["kind"], re.compile(d["regex"], flags)) for d in data.get("definitions", [])
        ),
        calls=re.compile(data["calls"], flags) if data.get("calls") else None,
        bare_calls=re.compile(data["bare_calls"], flags) if data.get("bare_calls") else None,
        call_kind=data.get("call_kind", "call"),
        keywords=frozenset(k.lower() for k in data.get("keywords", [])),
        builtins=frozenset(k.lower() for k in data.get("builtins", [])),
        globals_=frozenset(k.lower() for k in data.get("globals", [])),
        imports=tuple(
            ImportRule(i["kind"], re.compile(i["regex"], flags)) for i in data.get("imports", [])
        ),
        regions=tuple(re.compile(r["regex"], re.MULTILINE) for r in data.get("regions", [])),
        scope=data.get("scope", "none"),
        doc_position=data.get("doc_position", "before"),
        file_kind=data.get("file_kind", "module"),
        index_syntax=bool(data.get("index_syntax", False)),
    )


def profile_for(language: str | None) -> Profile:
    mapping = _raw()["languages"]
    return profile(mapping.get(language or "", "default"))


# --- masking ---------------------------------------------------------------------------------


def mask(text: str, prof: Profile) -> tuple[str, str, list[tuple[int, int]]]:
    """Blank comments (and, in the second form, strings) with spaces, preserving newlines.

    Returns (text without comments, text without comments or strings, comment line ranges).
    """
    n = len(text)
    no_comments = list(text)
    no_strings = list(text)
    comment_lines: list[tuple[int, int]] = []
    line = 1
    line_start = 0
    i = 0

    def blank(buf: list[str], start: int, end: int) -> None:
        for k in range(start, end):
            if buf[k] != "\n":
                buf[k] = " "

    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            line_start = i + 1
            i += 1
            continue
        # Block comments.
        matched = False
        for open_, close in prof.block_comments:
            if text.startswith(open_, i):
                if prof.block_comment_alone:
                    eol = text.find("\n", i)
                    eol = n if eol < 0 else eol
                    if text[line_start:eol].strip() != open_:
                        continue
                end = text.find(close, i + len(open_))
                end = n if end < 0 else end + len(close)
                start_line = line
                line += text.count("\n", i, end)
                comment_lines.append((start_line, line))
                blank(no_comments, i, end)
                blank(no_strings, i, end)
                nl = text.rfind("\n", i, end)
                if nl >= 0:
                    line_start = nl + 1
                i = end
                matched = True
                break
        if matched:
            continue
        # Line comments.
        for marker in prof.line_comments:
            if text.startswith(marker, i):
                end = text.find("\n", i)
                end = n if end < 0 else end
                comment_lines.append((line, line))
                blank(no_comments, i, end)
                blank(no_strings, i, end)
                i = end
                matched = True
                break
        if matched:
            continue
        # Strings (only blanked in the second buffer).
        for delim in prof.strings:
            if text.startswith(delim, i):
                if (
                    prof.matlab_transpose
                    and delim == "'"
                    and i > 0
                    and (text[i - 1].isalnum() or text[i - 1] in "_)]}.'")
                ):
                    break  # transpose operator, not a string
                j = i + len(delim)
                while j < n:
                    if prof.string_escape and text.startswith(prof.string_escape, j):
                        j += len(prof.string_escape) + 1
                        continue
                    if text.startswith(delim, j):
                        j += len(delim)
                        break
                    if text[j] == "\n" and len(delim) == 1 and delim != "`":
                        break  # unterminated single-line string: stop at the line end
                    j += 1
                blank(no_strings, i + len(delim), max(i + len(delim), j - len(delim)))
                line += text.count("\n", i, j)
                nl = text.rfind("\n", i, j)
                if nl >= 0:
                    line_start = nl + 1
                i = j
                matched = True
                break
        if matched:
            continue
        i += 1
    return "".join(no_comments), "".join(no_strings), _merge_ranges(comment_lines)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


# --- helpers ---------------------------------------------------------------------------------


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for idx, ch in enumerate(text):
        if ch == "\n":
            offsets.append(idx + 1)
    return offsets


def _line_of(offsets: list[int], pos: int) -> int:
    return bisect.bisect_right(offsets, pos)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def split_params(params: str | None) -> list[dict[str, Any]]:
    if not params or not params.strip():
        return []
    parts: list[str] = []
    depth = 0
    current = []
    for ch in params:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    result = []
    for raw in parts:
        item = raw.strip()
        if not item or item in ("void", "..."):
            continue
        default = None
        if "=" in item:
            item, default = item.split("=", 1)
            item, default = item.strip(), default.strip()
        type_ = None
        if ":" in item and "::" not in item:
            name_part, type_ = item.split(":", 1)
            name_part, type_ = name_part.strip(), type_.strip()
        else:
            tokens = _IDENT.findall(item)
            name_part = tokens[-1] if tokens else item
            rest = item[: item.rfind(name_part)].strip(" *&") if tokens else ""
            type_ = rest or None
        name = name_part.lstrip("*&$@").strip()
        entry: dict[str, Any] = {"name": name}
        if type_:
            entry["type"] = type_
        if default is not None:
            entry["default"] = default[:80]
        result.append(entry)
    return result


def _normalize_doc(lines: list[str], markers: tuple[str, ...]) -> str | None:
    cleaned: list[str] = []
    for raw in lines:
        s = raw.strip()
        for marker in sorted(markers, key=len, reverse=True):
            if s.startswith(marker):
                s = s[len(marker) :]
                break
        s = s.strip(" \t*/-")
        cleaned.append(s)
    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    paragraph: list[str] = []
    for s in cleaned:
        if not s:
            if paragraph:
                break
            continue
        paragraph.append(s)
    text = " ".join(paragraph).strip()
    if not text:
        return None
    return text[:MAX_DOC_CHARS]


# --- analysis --------------------------------------------------------------------------------


def analyze(key: str, text: str, language: str | None) -> FileAnalysis:
    prof = profile_for(language)
    lines = text.split("\n")
    n_lines = len(lines) if text else 0
    if text.endswith("\n"):
        n_lines -= 1
    result = FileAnalysis(
        key=key,
        language=language,
        tier="C",
        adapter=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        n_lines=max(n_lines, 0),
    )
    if not text.strip():
        return result
    if any(len(line) > MAX_LINE_CHARS for line in lines):
        result.notes.append("long lines truncated for analysis")
        text = "\n".join(line[:MAX_LINE_CHARS] for line in lines)
        lines = text.split("\n")

    no_comments, masked, comment_ranges = mask(text, prof)
    comment_only = _comment_only_lines(text, no_comments)
    offsets = _line_offsets(masked)
    masked_lines = masked.split("\n")
    stem = key.rsplit("/", 1)[-1]
    stem = stem[: stem.rfind(".")] if "." in stem[1:] else stem

    # Regions first, on raw lines.
    regions: list[Symbol] = []
    for rx in prof.regions:
        for m in rx.finditer(text):
            line_no = _line_of(offsets, m.start())
            title = (m.group("title") or "").strip() or f"region line {line_no}"
            regions.append(
                Symbol(
                    name=title,
                    qualname=f"region:{line_no}",
                    kind="region",
                    line=line_no,
                    end_line=line_no,
                    end_exact=False,
                    signature=title,
                )
            )

    # Definitions.
    defs: list[tuple[int, re.Match[str], DefRule]] = []
    for rule in prof.definitions:
        for m in rule.regex.finditer(masked):
            defs.append((m.start(), m, rule))
    defs.sort(key=lambda item: item[0])
    seen_name_positions: set[int] = set()
    symbols: list[Symbol] = []
    for _pos, m, rule in defs:
        name = (m.group("name") or "").strip().strip('"')
        if not name or name.lower() in prof.keywords:
            continue
        if m.start("name") in seen_name_positions:
            continue
        seen_name_positions.add(m.start("name"))
        line_no = _line_of(offsets, m.start("name"))
        end_line, exact = _span_end(
            prof, masked, masked_lines, offsets, line_no, m.end(), rule.kind
        )
        params_raw = None
        for group in ("params", "params2"):
            if group in m.groupdict() and m.group(group):
                params_raw = m.group(group)
                break
        returns = (
            m.group("returns").strip()
            if "returns" in m.groupdict() and m.group("returns")
            else None
        )
        if returns and returns.startswith("[") and returns.endswith("]"):
            returns = [r.strip() for r in returns[1:-1].replace(";", ",").split(",") if r.strip()]
        sig = lines[line_no - 1].strip()
        if sig.endswith("{"):
            sig = sig[:-1].rstrip()
        if sig.endswith(":") and prof.scope == "indent":
            sig = sig[:-1]
        visibility = (
            "private"
            if (
                name.startswith("_")
                or re.match(r"^\s*(?:static|private|local)\b", lines[line_no - 1])
            )
            else "public"
        )
        decorators = _decorators(lines, line_no) if prof.scope == "indent" else []
        doc = _doc_for(prof, lines, comment_only, comment_ranges, line_no, end_line)
        content = "\n".join(ln.rstrip() for ln in lines[line_no - 1 : end_line])
        symbols.append(
            Symbol(
                name=name,
                qualname=name,
                kind=rule.kind,
                line=line_no,
                end_line=end_line,
                end_exact=exact,
                signature=sig[:300],
                params=split_params(params_raw),
                returns=returns,
                doc=doc,
                visibility=visibility,
                decorators=decorators,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
        )

    # Parents and qualified names: innermost container whose span holds the definition line.
    symbols.extend(regions)
    symbols.sort(key=lambda s: (s.line, s.end_line * -1))
    stack: list[Symbol] = []
    for sym in symbols:
        while stack and not (stack[-1].line < sym.line <= stack[-1].end_line):
            stack.pop()
        if stack:
            sym.parent = stack[-1].qualname
            sym.qualname = f"{stack[-1].qualname}.{sym.name}"
        if sym.kind in CONTAINER_KINDS or sym.end_line > sym.line:
            stack.append(sym)

    # File-level symbol: every file gets one when it has code outside definitions or no definitions.
    def_name_spans: set[tuple[int, str]] = {(s.line, s.name) for s in symbols}
    starts = [s.line for s in symbols]

    def enclosing(line_no: int) -> Symbol | None:
        idx = bisect.bisect_right(starts, line_no) - 1
        best = None
        while idx >= 0:
            cand = symbols[idx]
            if cand.line <= line_no <= cand.end_line and cand.kind != "region":
                best = cand
                break
            idx -= 1
        return best

    calls: list[CallSite] = []
    assigned = _assigned_names(masked, symbols) if prof.index_syntax else frozenset()
    if prof.calls is not None:
        for m in prof.calls.finditer(masked):
            full = m.group("name")
            line_no = _line_of(offsets, m.start("name"))
            name, qualifier = _split_qualified(full)
            if not name or name.lower() in prof.keywords or full.lower() in prof.keywords:
                continue
            if (line_no, name) in def_name_spans and m.start("name") in seen_name_positions:
                continue
            if (line_no, name) in def_name_spans:
                continue
            col = m.start("name") - offsets[line_no - 1] + 1
            owner = enclosing(line_no)
            kind = "index" if (qualifier is None and name in assigned) else prof.call_kind
            calls.append(
                CallSite(
                    caller=owner.qualname if owner else None,
                    name=name,
                    qualifier=qualifier,
                    line=line_no,
                    col=col,
                    kind=kind,
                )
            )
    if prof.bare_calls is not None:
        for m in prof.bare_calls.finditer(masked):
            name = m.group("name")
            if name.lower() in prof.keywords:
                continue
            line_no = _line_of(offsets, m.start("name"))
            if (line_no, name) in def_name_spans:
                continue
            col = m.start("name") - offsets[line_no - 1] + 1
            owner = enclosing(line_no)
            calls.append(
                CallSite(
                    caller=owner.qualname if owner else None,
                    name=name,
                    qualifier=None,
                    line=line_no,
                    col=col,
                    kind="bare",
                )
            )

    has_file_level_code = any(c.caller is None for c in calls)
    file_symbol_needed = has_file_level_code or not any(s.kind != "region" for s in symbols)
    if file_symbol_needed:
        kind = "script" if prof.file_kind == "script" else "module"
        doc = _leading_comment(prof, lines, comment_only, comment_ranges)
        content = "\n".join(ln.rstrip() for ln in lines)
        file_sym = Symbol(
            name=stem,
            qualname="(file)",
            kind=kind,
            line=1,
            end_line=max(n_lines, 1),
            end_exact=True,
            signature=f"{kind} {stem}",
            doc=doc,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        symbols.append(file_sym)
        for c in calls:
            if c.caller is None:
                c.caller = "(file)"

    # Imports on comment-free text so quoted module paths survive.
    for rule in prof.imports:
        for m in rule.regex.finditer(no_comments):
            module = (m.group("module") or "").strip()
            if not module:
                continue
            names_raw = m.group("names") if "names" in m.groupdict() else None
            names: list[str] = []
            alias = m.group("alias") if "alias" in m.groupdict() else None
            if names_raw:
                items = [
                    x.strip().strip("{}() ")
                    for x in names_raw.replace("(", "").replace(")", "").split(",")
                ]
                aliases: list[str] = []
                for item in items:
                    if not item:
                        continue
                    base, _, as_name = item.partition(" as ")
                    names.append(base.strip())
                    if as_name.strip():
                        aliases.append(as_name.strip())
                if len(aliases) == 1 and alias is None:
                    alias = aliases[0]
            line_no = _line_of(_line_offsets(no_comments), m.start())
            result.imports.append(
                Import(
                    module=module,
                    line=line_no,
                    kind=rule.kind,
                    names=[x for x in names if x],
                    alias=alias,
                    relative=module.startswith("."),
                    raw=m.group(0).strip()[:200],
                )
            )

    result.symbols = sorted(symbols, key=lambda s: (s.line, s.qualname))
    result.calls = calls
    return result


_ASSIGN_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*(?:\([^()]*\)|\{[^{}]*\})?\s*=(?!=)")
_MULTI_ASSIGN_RE = re.compile(r"\[([^\]]*)\]\s*=(?!=)")
_FOR_RE = re.compile(r"for\s+([A-Za-z_]\w*)\s*=", re.IGNORECASE)


def _assigned_names(masked: str, symbols: list[Symbol]) -> frozenset[str]:
    """Names that are variables in this file: assigned, loop variables, parameters, returns."""
    names: set[str] = set()
    for m in _ASSIGN_RE.finditer(masked):
        names.add(m.group(1))
    for m in _MULTI_ASSIGN_RE.finditer(masked):
        names.update(_IDENT.findall(m.group(1)))
    for m in _FOR_RE.finditer(masked):
        names.add(m.group(1))
    for sym in symbols:
        names.update(p["name"] for p in sym.params)
        if isinstance(sym.returns, list):
            names.update(sym.returns)
        elif isinstance(sym.returns, str) and _IDENT.fullmatch(sym.returns):
            names.add(sym.returns)
    return frozenset(names)


def _split_qualified(full: str) -> tuple[str, str | None]:
    token = full.replace("->", ".").replace("::", ".")
    if "." in token:
        qualifier, name = token.rsplit(".", 1)
        return name, qualifier or None
    return token, None


def _decorators(lines: list[str], line_no: int) -> list[str]:
    found: list[str] = []
    idx = line_no - 2
    while idx >= 0 and lines[idx].strip().startswith("@"):
        found.append(lines[idx].strip()[:80])
        idx -= 1
    return list(reversed(found))


def _comment_only_lines(text: str, no_comments: str) -> list[str]:
    """Per line, only the characters that belong to comments (everything else blanked)."""
    newline = "\n"
    kept = []
    for ch, blank in zip(text, no_comments, strict=True):
        if ch == newline:
            kept.append(newline)
        elif blank == " " and ch != " ":
            kept.append(ch)  # a character that masking removed: it was inside a comment
        else:
            kept.append(" ")
    return "".join(kept).split(newline)


def _doc_for(
    prof: Profile,
    lines: list[str],
    comment_only: list[str],
    comment_ranges: list[tuple[int, int]],
    line_no: int,
    end_line: int,
) -> str | None:
    if prof.doc_position == "docstring":
        idx = line_no
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx < len(lines):
            s = lines[idx].strip()
            for delim in ('"""', "'''"):
                if s.startswith(delim):
                    body = s[3:]
                    if body.endswith(delim) and len(body) >= 3:
                        return _normalize_doc([body[:-3]], ())
                    collected = [body]
                    j = idx + 1
                    while j < len(lines) and delim not in lines[j]:
                        collected.append(lines[j])
                        j += 1
                    if j < len(lines):
                        collected.append(lines[j].split(delim)[0])
                    return _normalize_doc(collected, ())
        return None
    markers = (
        prof.line_comments
        + tuple(o for o, _ in prof.block_comments)
        + tuple(c for _, c in prof.block_comments)
    )
    if prof.doc_position == "after":
        for start, end in comment_ranges:
            if start == line_no + 1:
                return _normalize_doc(comment_only[start - 1 : end], markers)
        return None
    # before: a comment block ending on the previous line (decorators may sit between).
    probe = line_no - 1
    while probe >= 1 and lines[probe - 1].strip().startswith("@"):
        probe -= 1
    for start, end in comment_ranges:
        if end == probe:
            return _normalize_doc(comment_only[start - 1 : end], markers)
    return None


def _leading_comment(
    prof: Profile, lines: list[str], comment_only: list[str], comment_ranges: list[tuple[int, int]]
) -> str | None:
    markers = (
        prof.line_comments
        + tuple(o for o, _ in prof.block_comments)
        + tuple(c for _, c in prof.block_comments)
    )
    first_code = 1
    while first_code <= len(lines) and (
        not lines[first_code - 1].strip() or lines[first_code - 1].startswith("#!")
    ):
        first_code += 1
    for start, end in comment_ranges:
        if start <= first_code + 1:
            return _normalize_doc(comment_only[start - 1 : end], markers)
        break
    return None


def _span_end(
    prof: Profile,
    masked: str,
    masked_lines: list[str],
    offsets: list[int],
    line_no: int,
    match_end: int,
    kind: str = "",
) -> tuple[int, bool]:
    total = len(masked_lines)
    if kind in ("macro", "target", "stage", "variable", "resource"):
        return line_no, True
    if prof.scope == "brace":
        # The opening brace must sit on the definition line or alone on the next line
        # (K&R style); anything further away belongs to a different construct.
        line_end = offsets[line_no] - 1 if line_no < len(offsets) else len(masked)
        brace = masked.find("{", offsets[line_no - 1], line_end)
        if brace < 0 and line_no < total and masked_lines[line_no].strip().startswith("{"):
            brace = masked.find("{", offsets[line_no])
        if brace < 0:
            return line_no, True
        depth = 0
        for pos in range(brace, len(masked)):
            ch = masked[pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return _line_of(offsets, pos), True
        return total, False
    if prof.scope == "indent":
        base = _indent(masked_lines[line_no - 1])
        last = line_no
        for idx in range(line_no, total):
            line = masked_lines[idx]
            if not line.strip():
                continue
            if _indent(line) <= base:
                break
            last = idx + 1
        return last, True
    if prof.scope == "end":
        base = _indent(masked_lines[line_no - 1])
        for idx in range(line_no, total):
            line = masked_lines[idx]
            if not line.strip():
                continue
            if _indent(line) <= base and any(r.regex.match(line) for r in prof.definitions):
                return idx, False
        return total, False
    return line_no, False
