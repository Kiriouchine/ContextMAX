# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`org-v1`: Org mode. Star headings, source and example blocks, links, includes, tables."""

from __future__ import annotations

import re

from contextmax.docs.adapters.common import decode, split_number, squash
from contextmax.docs.base import Block, DocumentTree

HEADING = re.compile(r"^(\*+)\s+(?:(?:TODO|DONE|NEXT|WAITING|CANCELLED)\s+)?(?:\[#[A-C]\]\s+)?(.*?)(?:\s+:[\w:@]+:)?\s*$")
KEYWORD = re.compile(r"^#\+([A-Za-z_]+):\s*(.*)$")
BEGIN = re.compile(r"^#\+BEGIN_([A-Za-z]+)(?:\s+(.*))?$", re.IGNORECASE)
LINK = re.compile(r"\[\[([^\]]+)\](?:\[([^\]]*)\])?\]")
ANCHOR = re.compile(r"<<([^>]+)>>")
LIST_ITEM = re.compile(r"^(\s*)([-+*]|\d+[.)])\s+(?:\[[ Xx-]\]\s+)?(.*)$")
URL = re.compile(r"(?<![\w\[])(https?://[^\s\]]+)")


class OrgAdapter:
    id = "org-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        text = decode(data)
        lines = text.split("\n")
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        i = 0
        n = len(lines)
        para: list[str] = []
        para_start = 0
        caption: str | None = None

        def flush() -> None:
            nonlocal para
            if para:
                body = squash(" ".join(para))
                if body:
                    tree.blocks.append(Block(kind="paragraph", text=self._clean(body), line=para_start, end_line=para_start + len(para) - 1))
                    self._inline(tree, body, para_start)
            para = []

        while i < n:
            line = lines[i]
            stripped = line.rstrip()
            m = HEADING.match(stripped)
            if m:
                flush()
                number, clean = split_number(m.group(2))
                tree.blocks.append(Block(kind="heading", text=clean, level=len(m.group(1)), number=number, line=i + 1, end_line=i + 1))
                i += 1
                continue
            m = BEGIN.match(stripped)
            if m:
                flush()
                kind, arg = m.group(1).upper(), (m.group(2) or "").strip()
                j = i + 1
                body: list[str] = []
                while j < n and not re.match(rf"^#\+END_{kind}\b", lines[j].rstrip(), re.IGNORECASE):
                    body.append(lines[j])
                    j += 1
                if kind in ("SRC", "EXAMPLE"):
                    lang = arg.split()[0] if (kind == "SRC" and arg) else None
                    tree.blocks.append(Block(kind="code", text="\n".join(body), lang=lang, line=i + 1, end_line=j + 1))
                elif kind != "COMMENT":
                    joined = squash(" ".join(b.strip() for b in body))
                    if joined:
                        tree.blocks.append(Block(kind="paragraph", text=self._clean(joined), line=i + 1, end_line=j + 1))
                        self._inline(tree, joined, i + 1)
                caption = None
                i = j + 1
                continue
            m = KEYWORD.match(stripped)
            if m:
                name, value = m.group(1).upper(), m.group(2).strip()
                if name == "TITLE":
                    tree.title = value
                    tree.blocks.append(Block(kind="title", text=value, line=i + 1, end_line=i + 1))
                elif name in ("AUTHOR", "DATE", "EMAIL", "LANGUAGE", "DESCRIPTION", "KEYWORDS"):
                    tree.metadata[name.lower()] = value
                elif name == "CAPTION":
                    caption = value
                elif name == "INCLUDE":
                    target = value.split()[0].strip('"') if value else ""
                    if target:
                        tree.blocks.append(Block(kind="include", text=target, target=target, line=i + 1, end_line=i + 1, extra={"command": "include"}))
                i += 1
                continue
            if stripped.strip() == ":PROPERTIES:":
                while i < n and lines[i].strip() != ":END:":
                    i += 1
                i += 1
                continue
            if stripped.lstrip().startswith("|"):
                flush()
                j = i
                rows: list[list[str]] = []
                while j < n and lines[j].lstrip().startswith("|"):
                    row = lines[j].strip()
                    if not row.startswith("|-"):
                        rows.append([c.strip() for c in row.strip("|").split("|")])
                    j += 1
                tree.blocks.append(Block(kind="table", text=caption or "", rows=rows, line=i + 1, end_line=j))
                caption = None
                i = j
                continue
            if stripped.startswith("#"):
                i += 1
                continue
            if not stripped.strip():
                flush()
                i += 1
                continue
            m = LIST_ITEM.match(stripped)
            if m:
                flush()
                depth = len(m.group(1)) // 2 + 1
                body_text = squash(m.group(3))
                tree.blocks.append(Block(kind="list_item", text=self._clean(body_text), level=depth, line=i + 1, end_line=i + 1))
                self._inline(tree, body_text, i + 1)
                i += 1
                continue
            if not para:
                para_start = i + 1
            para.append(stripped.strip())
            i += 1
        flush()
        if tree.title is None:
            first = next((b for b in tree.blocks if b.kind == "heading"), None)
            if first:
                tree.title = first.text
        return tree

    @staticmethod
    def _clean(body: str) -> str:
        """Paragraph text for search: links reduced to their description, anchors removed."""
        clean = LINK.sub(lambda m: m.group(2) or m.group(1), body)
        return squash(ANCHOR.sub("", clean))

    @staticmethod
    def _inline(tree: DocumentTree, body: str, line: int) -> None:
        for m in LINK.finditer(body):
            target, label = m.group(1), m.group(2) or m.group(1)
            if target.startswith("file:"):
                target = target[5:]
            if target.startswith("#") or target.startswith("*"):
                tree.blocks.append(Block(kind="ref", text=label, target=target.lstrip("#*").strip(), line=line, end_line=line, extra={"ref_kind": "label"}))
            elif target.startswith(("http://", "https://", "mailto:")) or "." in target.rsplit("/", 1)[-1] or "/" in target:
                tree.blocks.append(Block(kind="link", text=label, target=target, line=line, end_line=line))
            else:
                tree.blocks.append(Block(kind="ref", text=label, target=target, line=line, end_line=line, extra={"ref_kind": "label"}))
        for m in ANCHOR.finditer(body):
            tree.blocks.append(Block(kind="label", text=m.group(1), target=m.group(1), line=line, end_line=line))
        for m in URL.finditer(body):
            if f"[[{m.group(1)}" not in body:
                tree.blocks.append(Block(kind="link", text=m.group(1), target=m.group(1), line=line, end_line=line))
