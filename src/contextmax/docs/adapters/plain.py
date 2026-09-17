# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`plain-v1`: paragraphs, with headings only where the text makes them unmistakable
(underlined titles, or numbered short lines such as "3.1 Scope")."""

from __future__ import annotations

import re

from contextmax.docs.adapters.common import decode, split_number, squash
from contextmax.docs.base import Block, DocumentTree

UNDERLINE = re.compile(r"^\s*(=+|-+|~+|\*+)\s*$")
NUMBERED = re.compile(r"^\s*((?:\d+\.)+\d*|\d+)\s+([A-Z][^\n]{2,80})$")


class PlainAdapter:
    id = "plain-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        text = decode(data)
        lines = text.split("\n")
        tree = DocumentTree(
            key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism
        )
        n = len(lines)
        i = 0
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
            paragraph = []

        while i < n:
            line = lines[i]
            lineno = i + 1
            stripped = line.strip()
            if (
                stripped
                and i + 1 < n
                and UNDERLINE.match(lines[i + 1])
                and len(lines[i + 1].strip()) >= max(3, len(stripped) // 2)
                and not paragraph
            ):
                flush(lineno - 1)
                level = 1 if lines[i + 1].strip()[0] in "=*" else 2
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
            m = NUMBERED.match(line)
            if (
                m
                and not paragraph
                and (i + 1 >= n or not lines[i + 1].strip() or i == 0 or not lines[i - 1].strip())
            ):
                flush(lineno - 1)
                number = m.group(1).rstrip(".")
                level = number.count(".") + 1
                tree.blocks.append(
                    Block(
                        kind="heading",
                        text=squash(m.group(2)),
                        line=lineno,
                        end_line=lineno,
                        level=level,
                        number=number,
                    )
                )
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
        if tree.title is None:
            first = next((b for b in tree.blocks if b.kind == "paragraph"), None)
            if first and len(first.text) <= 80 and first.line == 1:
                tree.title = first.text
        return tree
