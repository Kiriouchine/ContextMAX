# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`markdown-v1`: CommonMark-style structure with the standard library only.

Headings (ATX and setext), fenced code, pipe tables, list items, links and images, reference
definitions, footnotes, front matter title. Inline code spans keep their backticks so the
document-to-code linker can weigh them.
"""

from __future__ import annotations

import re

from contextmax.docs.adapters.common import decode, split_number, squash
from contextmax.docs.base import Block, DocumentTree

ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SETEXT = re.compile(r"^(=+|-+)\s*$")
FENCE = re.compile(r"^(```+|~~~+)\s*([\w+-]*)\s*$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REF_LINK = re.compile(r"(!?)\[([^\]]+)\]\[([^\]]*)\]")
REF_DEF = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(\S+)")
FOOTNOTE_DEF = re.compile(r"^\s{0,3}\[\^([^\]]+)\]:\s*(.*)$")
FOOTNOTE_REF = re.compile(r"\[\^([^\]]+)\]")
AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


class MarkdownAdapter:
    id = "markdown-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        text = HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), decode(data))
        lines = text.split("\n")
        tree = DocumentTree(
            key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism
        )
        i = 0
        n = len(lines)
        # Front matter.
        if n and lines[0].strip() == "---":
            j = 1
            while j < n and lines[j].strip() not in ("---", "..."):
                m = re.match(r"^\s*title\s*:\s*(.+?)\s*$", lines[j])
                if m:
                    tree.title = m.group(1).strip("\"'")
                j += 1
            if j < n:
                i = j + 1
        refs: dict[str, str] = {}
        for line in lines:
            m = REF_DEF.match(line)
            if m:
                refs[m.group(1).lower()] = m.group(2)
        paragraph: list[str] = []
        para_start = 0

        def flush(end_line: int) -> None:
            nonlocal paragraph
            if paragraph:
                body = squash(" ".join(paragraph))
                if body:
                    tree.blocks.append(
                        Block(kind="paragraph", text=body, line=para_start, end_line=end_line)
                    )
                    self._inline(tree, body, para_start, refs)
            paragraph = []

        while i < n:
            line = lines[i]
            lineno = i + 1
            stripped = line.strip()
            fence = FENCE.match(stripped)
            if fence:
                flush(lineno - 1)
                marker = fence.group(1)
                lang = fence.group(2) or None
                j = i + 1
                body: list[str] = []
                while j < n and not lines[j].strip().startswith(marker[0] * 3):
                    body.append(lines[j])
                    j += 1
                tree.blocks.append(
                    Block(
                        kind="code",
                        text="\n".join(body),
                        line=lineno,
                        end_line=min(j + 1, n),
                        lang=lang,
                    )
                )
                i = j + 1
                continue
            m = ATX.match(line)
            if m:
                flush(lineno - 1)
                title = squash(m.group(2))
                number, clean = split_number(title)
                tree.blocks.append(
                    Block(
                        kind="heading",
                        text=clean,
                        line=lineno,
                        end_line=lineno,
                        level=len(m.group(1)),
                        number=number,
                    )
                )
                if tree.title is None and len(m.group(1)) == 1:
                    tree.title = clean
                i += 1
                continue
            if (
                i + 1 < n
                and stripped
                and SETEXT.match(lines[i + 1])
                and not paragraph
                and not LIST_ITEM.match(line)
            ):
                level = 1 if lines[i + 1].strip().startswith("=") else 2
                number, clean = split_number(squash(stripped))
                tree.blocks.append(
                    Block(
                        kind="heading",
                        text=clean,
                        line=lineno,
                        end_line=lineno + 1,
                        level=level,
                        number=number,
                    )
                )
                if tree.title is None and level == 1:
                    tree.title = clean
                i += 2
                continue
            if "|" in line and i + 1 < n and TABLE_SEP.match(lines[i + 1]):
                flush(lineno - 1)
                rows: list[list[str]] = []
                j = i
                while j < n and "|" in lines[j] and lines[j].strip():
                    if not TABLE_SEP.match(lines[j]):
                        cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                        rows.append(cells)
                    j += 1
                tree.blocks.append(
                    Block(
                        kind="table",
                        text="\n".join("\t".join(r) for r in rows),
                        line=lineno,
                        end_line=j,
                        rows=rows,
                    )
                )
                i = j
                continue
            fm = FOOTNOTE_DEF.match(line)
            if fm:
                flush(lineno - 1)
                tree.blocks.append(
                    Block(
                        kind="footnote",
                        text=squash(fm.group(2)),
                        line=lineno,
                        end_line=lineno,
                        target=fm.group(1),
                    )
                )
                i += 1
                continue
            if REF_DEF.match(line):
                i += 1
                continue
            lm = LIST_ITEM.match(line)
            if lm:
                flush(lineno - 1)
                body = squash(lm.group(3))
                tree.blocks.append(
                    Block(
                        kind="list_item",
                        text=body,
                        line=lineno,
                        end_line=lineno,
                        level=len(lm.group(1)) // 2 + 1,
                    )
                )
                self._inline(tree, body, lineno, refs)
                i += 1
                continue
            if not stripped:
                flush(lineno - 1)
                i += 1
                continue
            if not paragraph:
                para_start = lineno
            paragraph.append(stripped)
            i += 1
        flush(n)
        return tree

    def _inline(self, tree: DocumentTree, body: str, line: int, refs: dict[str, str]) -> None:
        for m in LINK.finditer(body):
            kind = "figure" if m.group(1) == "!" else "link"
            tree.blocks.append(
                Block(
                    kind=kind, text=squash(m.group(2)), line=line, end_line=line, target=m.group(3)
                )
            )
        for m in REF_LINK.finditer(body):
            ident = (m.group(3) or m.group(2)).lower()
            target = refs.get(ident)
            if target:
                kind = "figure" if m.group(1) == "!" else "link"
                tree.blocks.append(
                    Block(
                        kind=kind, text=squash(m.group(2)), line=line, end_line=line, target=target
                    )
                )
        for m in AUTOLINK.finditer(body):
            tree.blocks.append(
                Block(kind="link", text=m.group(1), line=line, end_line=line, target=m.group(1))
            )
        for m in FOOTNOTE_REF.finditer(body):
            tree.blocks.append(
                Block(
                    kind="ref",
                    text=m.group(1),
                    line=line,
                    end_line=line,
                    target=m.group(1),
                    extra={"ref_kind": "footnote"},
                )
            )
