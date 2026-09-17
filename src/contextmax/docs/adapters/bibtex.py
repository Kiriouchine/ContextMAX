# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`bibtex-v1`: BibTeX entries as reference blocks, parsed with the standard library."""

from __future__ import annotations

import re

from contextmax.docs.adapters.common import decode, squash
from contextmax.docs.base import Block, DocumentTree

ENTRY = re.compile(r"@(?P<type>[A-Za-z]+)\s*[{(]\s*(?P<key>[^,\s]+)\s*,", re.S)
FIELD = re.compile(r"(?P<name>[A-Za-z_-]+)\s*=\s*", re.S)


def _balanced_value(text: str, pos: int) -> tuple[str, int]:
    """Read a field value at `pos`: {…} with nesting, "…", or a bare token."""
    if pos >= len(text):
        return "", pos
    ch = text[pos]
    if ch == "{":
        depth = 0
        i = pos
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[pos + 1 : i], i + 1
            i += 1
        return text[pos + 1 :], len(text)
    if ch == '"':
        i = pos + 1
        while i < len(text) and text[i] != '"':
            i += 1
        return text[pos + 1 : i], i + 1
    m = re.match(r"[^,}\n]+", text[pos:])
    value = m.group(0) if m else ""
    return value, pos + len(value)


def parse_entries(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for m in ENTRY.finditer(text):
        entry_type = m.group("type").lower()
        if entry_type in ("comment", "preamble", "string"):
            continue
        fields: dict[str, str] = {"type": entry_type, "key": m.group("key")}
        pos = m.end()
        depth = 1
        while pos < len(text) and depth > 0:
            fm = FIELD.match(text, pos)
            if fm:
                value, pos = _balanced_value(text, fm.end())
                fields[fm.group("name").lower()] = squash(value.replace("{", "").replace("}", "").replace("\\&", "&"))
                continue
            ch = text[pos]
            if ch == "}":
                depth -= 1
            elif ch == "{":
                depth += 1
            pos += 1
        entries.append(fields)
    return entries


class BibtexAdapter:
    id = "bibtex-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        text = decode(data)
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        offsets = [0]
        for idx, ch in enumerate(text):
            if ch == "\n":
                offsets.append(idx + 1)
        entries = parse_entries(text)
        tree.title = key.rsplit("/", 1)[-1]
        tree.metadata["n_entries"] = len(entries)
        for m, entry in zip(ENTRY.finditer(text), entries, strict=False):
            import bisect

            line = bisect.bisect_right(offsets, m.start())
            title = entry.get("title", "")
            authors = entry.get("author", "")
            year = entry.get("year", "")
            label = " · ".join(x for x in (authors[:80], year, title) if x)
            tree.blocks.append(Block(kind="bibentry", text=label, line=line, end_line=line, target=entry["key"], extra={
                "entry_type": entry["type"], "title": title, "authors": authors, "year": year,
                "doi": entry.get("doi", ""), "url": entry.get("url", ""), "file": entry.get("file", ""),
                "journal": entry.get("journal", "") or entry.get("booktitle", ""),
            }))
            tree.blocks.append(Block(kind="paragraph", text=f"[{entry['key']}] {label}", line=line, end_line=line))
        return tree
