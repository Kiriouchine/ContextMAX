# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`asciidoc-v1`: AsciiDoc. `=` headings, delimited blocks, images, includes, links, anchors."""

from __future__ import annotations

import re

from contextmax.docs.adapters.common import decode, split_number, squash
from contextmax.docs.base import Block, DocumentTree

HEADING = re.compile(r"^(=+)\s+(.+?)\s*$")
ATTRIBUTE = re.compile(r"^:([\w-]+):\s*(.*)$")
ANCHOR = re.compile(r"^\[\[([^\],]+)(?:,[^\]]*)?\]\]\s*$")
BLOCK_ATTR = re.compile(r"^\[([^\]]*)\]\s*$")
DELIMITERS = {"----": "listing", "....": "literal", "====": "example", "****": "sidebar", "____": "quote",
              "++++": "passthrough", "////": "comment", "--": "open", "|===": "table"}
LIST_ITEM = re.compile(r"^(\*+|-|\.+|\d+\.)\s+(.*)$")
MACRO = re.compile(r"(?<!\w)(image|include|link|xref|video|audio)::?([^\[\s]+)\[([^\]]*)\]")
XREF = re.compile(r"<<([^,>]+)(?:,([^>]*))?>>")
URL = re.compile(r"(?<![\w\[:])(https?://[^\s\[\]<>]+)(?:\[([^\]]*)\])?")
FOOTNOTE = re.compile(r"footnote(?:ref)?:([\w-]*)\[([^\]]*)\]")


class AsciidocAdapter:
    id = "asciidoc-v1"
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
        pending_attr: str | None = None
        pending_caption: str | None = None

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
            if m and not para:
                flush()
                level = len(m.group(1))
                number, clean = split_number(m.group(2))
                if level == 1 and tree.title is None and not any(b.kind == "heading" for b in tree.blocks):
                    tree.title = clean
                    tree.blocks.append(Block(kind="title", text=clean, line=i + 1, end_line=i + 1))
                else:
                    tree.blocks.append(Block(kind="heading", text=clean, level=level, number=number, line=i + 1, end_line=i + 1))
                pending_attr = pending_caption = None
                i += 1
                continue
            m = ATTRIBUTE.match(stripped)
            if m and not para:
                tree.metadata[m.group(1)] = m.group(2)
                if m.group(1) == "title" and tree.title is None:
                    tree.title = m.group(2)
                i += 1
                continue
            m = ANCHOR.match(stripped)
            if m:
                flush()
                tree.blocks.append(Block(kind="label", text=m.group(1), target=m.group(1), line=i + 1, end_line=i + 1))
                i += 1
                continue
            if stripped in DELIMITERS or (len(stripped) >= 4 and stripped[:4] in DELIMITERS and len(set(stripped)) == 1):
                flush()
                marker = stripped if stripped in DELIMITERS else stripped[:4]
                kind = DELIMITERS[marker]
                j = i + 1
                body: list[str] = []
                while j < n and lines[j].rstrip() != stripped:
                    body.append(lines[j])
                    j += 1
                if kind == "comment":
                    pass
                elif kind in ("listing", "literal") or (pending_attr or "").startswith("source"):
                    lang = None
                    if pending_attr and pending_attr.startswith("source"):
                        parts = [p.strip() for p in pending_attr.split(",")]
                        lang = parts[1] if len(parts) > 1 and parts[1] else None
                    tree.blocks.append(Block(kind="code", text="\n".join(body), lang=lang, line=i + 1, end_line=j + 1))
                elif kind == "table":
                    rows = [[c.strip() for c in b.strip().strip("|").split("|")] for b in body if b.strip().startswith("|")]
                    tree.blocks.append(Block(kind="table", text=pending_caption or "", rows=rows, line=i + 1, end_line=j + 1))
                else:
                    joined = squash(" ".join(b.strip() for b in body))
                    if joined:
                        tree.blocks.append(Block(kind="paragraph", text=self._clean(joined), line=i + 1, end_line=j + 1))
                        self._inline(tree, joined, i + 1)
                pending_attr = pending_caption = None
                i = j + 1
                continue
            m = BLOCK_ATTR.match(stripped)
            if m and not para:
                pending_attr = m.group(1)
                i += 1
                continue
            if stripped.startswith(".") and len(stripped) > 1 and stripped[1] not in ". " and not para:
                pending_caption = stripped[1:].strip()
                i += 1
                continue
            if stripped.startswith("//"):
                i += 1
                continue
            mm = MACRO.match(stripped)
            if mm and mm.group(1) in ("image", "include", "video", "audio") and "::" in stripped[: mm.end()]:
                flush()
                name, target, attrs = mm.group(1), mm.group(2), mm.group(3)
                if name == "include":
                    tree.blocks.append(Block(kind="include", text=target, target=target, line=i + 1, end_line=i + 1, extra={"command": "include"}))
                else:
                    caption = pending_caption or attrs.split(",")[0]
                    tree.blocks.append(Block(kind="figure", text=caption, target=target, line=i + 1, end_line=i + 1))
                pending_attr = pending_caption = None
                i += 1
                continue
            if not stripped:
                flush()
                i += 1
                continue
            m = LIST_ITEM.match(stripped)
            if m:
                flush()
                marker = m.group(1)
                depth = len(marker) if marker[0] in "*." else 1
                body_text = squash(m.group(2))
                tree.blocks.append(Block(kind="list_item", text=self._clean(body_text), level=depth, line=i + 1, end_line=i + 1))
                self._inline(tree, body_text, i + 1)
                i += 1
                continue
            if not para:
                para_start = i + 1
            para.append(stripped)
            i += 1
        flush()
        if tree.title is None:
            first = next((b for b in tree.blocks if b.kind == "heading"), None)
            if first:
                tree.title = first.text
        return tree

    @staticmethod
    def _clean(body: str) -> str:
        """Paragraph text for search: macros, cross-references and URLs reduced to their label."""
        clean = MACRO.sub(lambda m: (m.group(3).split(",")[0] if m.group(3) else m.group(2)), body)
        clean = XREF.sub(lambda m: (m.group(2) or m.group(1)).strip(), clean)
        clean = URL.sub(lambda m: m.group(2) or m.group(1), clean)
        clean = FOOTNOTE.sub("", clean)
        return squash(clean)

    @staticmethod
    def _inline(tree: DocumentTree, body: str, line: int) -> None:
        for m in MACRO.finditer(body):
            name, target, attrs = m.group(1), m.group(2), m.group(3)
            label = attrs.split(",")[0] if attrs else target
            if name in ("link", "xref"):
                tree.blocks.append(Block(kind="link", text=label, target=target, line=line, end_line=line))
            elif name == "image":
                tree.blocks.append(Block(kind="figure", text=label, target=target, line=line, end_line=line))
        for m in XREF.finditer(body):
            tree.blocks.append(Block(kind="ref", text=(m.group(2) or m.group(1)).strip(), target=m.group(1).strip(),
                                     line=line, end_line=line, extra={"ref_kind": "label"}))
        for m in URL.finditer(body):
            tree.blocks.append(Block(kind="link", text=m.group(2) or m.group(1), target=m.group(1), line=line, end_line=line))
        for idx, m in enumerate(FOOTNOTE.finditer(body), start=1):
            tree.blocks.append(Block(kind="footnote", text=m.group(2), target=m.group(1) or f"fn{line}-{idx}", line=line, end_line=line))
