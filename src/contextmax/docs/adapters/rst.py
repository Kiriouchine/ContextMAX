# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`rst-v1`: reStructuredText. Headings by adornment (levels in order of first appearance),
directives for code, images, figures, includes and toctrees, literal blocks, links, labels."""

from __future__ import annotations

import re

from contextmax.docs.adapters.common import decode, split_number, squash
from contextmax.docs.base import Block, DocumentTree

ADORNMENT = set("=-`:'\"~^_*+#<>")
DIRECTIVE = re.compile(r"^\.\.\s+([A-Za-z][\w-]*)::\s*(.*)$")
EXPLICIT_TARGET = re.compile(r"^\.\.\s+_([^:]+):\s*(.*)$")
LIST_ITEM = re.compile(r"^(\s*)([-*+•]|\d+[.)]|#\.|[a-z][.)])\s+(.*)$")
INLINE_LINK = re.compile(r"`([^`<]*?)\s*<([^>`]+)>`_{1,2}")
ROLE_LINK = re.compile(r":(ref|doc|download|numref):`([^`]+)`")
NAMED_REF = re.compile(r"`([^`]+)`_(?!_)")
CODE_DIRECTIVES = {"code", "code-block", "sourcecode", "literalinclude", "highlight"}
FIGURE_DIRECTIVES = {"image", "figure"}
INCLUDE_DIRECTIVES = {"include", "literalinclude", "toctree"}
TEXT_DIRECTIVES = {"note", "warning", "tip", "important", "hint", "caution", "danger", "admonition", "seealso",
                   "topic", "sidebar", "epigraph", "versionadded", "versionchanged", "deprecated", "math"}


def _is_adornment(line: str) -> bool:
    stripped = line.rstrip()
    return len(stripped) >= 2 and len(set(stripped)) == 1 and stripped[0] in ADORNMENT


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


class RstAdapter:
    id = "rst-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        text = decode(data)
        lines = text.split("\n")
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        levels: dict[tuple[str, bool], int] = {}
        i = 0
        n = len(lines)
        para: list[str] = []
        para_start = 0

        def flush() -> None:
            nonlocal para
            if para:
                body = squash(" ".join(para))
                if body:
                    self._emit_text(tree, body, para_start, para_start + len(para) - 1)
            para = []

        while i < n:
            line = lines[i]
            # Overline + title + underline
            if _is_adornment(line) and i + 2 < n and _is_adornment(lines[i + 2]) and lines[i + 1].strip():
                title = lines[i + 1].strip()
                if len(line.rstrip()) >= len(title):
                    flush()
                    level = levels.setdefault((line[0], True), len(levels) + 1)
                    number, clean = split_number(title)
                    tree.blocks.append(Block(kind="heading", text=clean, level=level, number=number, line=i + 2, end_line=i + 3))
                    if tree.title is None:
                        tree.title = clean
                    i += 3
                    continue
            # Title + underline
            if line.strip() and i + 1 < n and _is_adornment(lines[i + 1]) and not _is_adornment(line) \
                    and len(lines[i + 1].rstrip()) >= len(line.rstrip()) and _indent(line) == 0:
                flush()
                level = levels.setdefault((lines[i + 1][0], False), len(levels) + 1)
                number, clean = split_number(line.strip())
                tree.blocks.append(Block(kind="heading", text=clean, level=level, number=number, line=i + 1, end_line=i + 2))
                if tree.title is None:
                    tree.title = clean
                i += 2
                continue
            m = DIRECTIVE.match(line)
            if m:
                flush()
                name, arg = m.group(1).lower(), m.group(2).strip()
                body, options, end = self._directive_body(lines, i + 1)
                if name in CODE_DIRECTIVES and name != "literalinclude":
                    tree.blocks.append(Block(kind="code", text="\n".join(body), lang=arg or None, line=i + 1, end_line=end))
                elif name in FIGURE_DIRECTIVES:
                    caption = squash(" ".join(body)) if name == "figure" else options.get("alt", "")
                    tree.blocks.append(Block(kind="figure", text=caption, target=arg, line=i + 1, end_line=end))
                elif name in INCLUDE_DIRECTIVES:
                    targets = [arg] if arg else []
                    if name == "toctree":
                        targets = [b.strip() for b in body if b.strip() and not b.strip().startswith(":")]
                    for target in targets:
                        clean_target = target.split("<")[-1].rstrip(">").strip() if "<" in target else target
                        tree.blocks.append(Block(kind="include", text=clean_target, target=clean_target, line=i + 1, end_line=end,
                                                 extra={"command": name}))
                elif name in TEXT_DIRECTIVES:
                    if arg:
                        tree.blocks.append(Block(kind="paragraph", text=arg, line=i + 1, end_line=i + 1))
                    if body:
                        self._emit_text(tree, squash(" ".join(body)), i + 1, end)
                elif name == "csv-table" or name == "list-table" or name == "table":
                    rows = [[c.strip() for c in b.split(",")] for b in body if b.strip() and not b.strip().startswith(":")]
                    tree.blocks.append(Block(kind="table", text=arg, rows=rows, line=i + 1, end_line=end))
                i = end + 1
                continue
            m = EXPLICIT_TARGET.match(line)
            if m:
                flush()
                label, target = m.group(1).strip("`"), m.group(2).strip()
                if target:
                    tree.blocks.append(Block(kind="link", text=label, target=target, line=i + 1, end_line=i + 1))
                else:
                    tree.blocks.append(Block(kind="label", text=label, target=label, line=i + 1, end_line=i + 1))
                i += 1
                continue
            if line.startswith(".. ") or line.strip() == "..":
                flush()
                i = self._directive_body(lines, i + 1)[2] + 1  # comment: skip its indented body
                continue
            if not line.strip():
                flush()
                i += 1
                continue
            m = LIST_ITEM.match(line)
            if m and _indent(line) < 4:
                flush()
                depth = _indent(line) // 2 + 1
                body_lines = [m.group(3)]
                j = i + 1
                while j < n and lines[j].strip() and _indent(lines[j]) > _indent(line) and not LIST_ITEM.match(lines[j]):
                    body_lines.append(lines[j].strip())
                    j += 1
                body = squash(" ".join(body_lines))
                tree.blocks.append(Block(kind="list_item", text=self._clean(body), level=depth, line=i + 1, end_line=j))
                self._emit_links(tree, body, i + 1)
                i = j
                continue
            if line.strip().startswith(("+-", "+=")) and set(line.strip()) <= set("+-=| "):
                flush()
                j = i
                rows: list[list[str]] = []
                while j < n and lines[j].strip().startswith(("+", "|")):
                    if lines[j].strip().startswith("|"):
                        rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                    j += 1
                tree.blocks.append(Block(kind="table", rows=rows, line=i + 1, end_line=j))
                i = j
                continue
            if not para:
                para_start = i + 1
            para.append(line.strip())
            if line.rstrip().endswith("::"):
                flush_text = squash(" ".join(para))[:-2].rstrip()
                para = []
                if flush_text and flush_text != ":":
                    self._emit_text(tree, flush_text, para_start, i + 1)
                body, _, end = self._directive_body(lines, i + 1)
                tree.blocks.append(Block(kind="code", text="\n".join(body), line=i + 2, end_line=end))
                i = end + 1
                continue
            i += 1
        flush()
        return tree

    @staticmethod
    def _directive_body(lines: list[str], start: int) -> tuple[list[str], dict[str, str], int]:
        """Indented body after a directive or literal marker: (body lines, :options:, last line no)."""
        i = start
        n = len(lines)
        while i < n and not lines[i].strip():
            i += 1
        if i >= n or _indent(lines[i]) == 0:
            return [], {}, start - 1 if start else 0
        base = _indent(lines[i])
        body: list[str] = []
        options: dict[str, str] = {}
        last = i
        while i < n and (not lines[i].strip() or _indent(lines[i]) >= base):
            if lines[i].strip():
                last = i
                stripped = lines[i][base:]
                om = re.match(r"^:([\w-]+):\s*(.*)$", stripped)
                if om and not body:
                    options[om.group(1)] = om.group(2)
                else:
                    body.append(stripped.rstrip())
            i += 1
        while body and not body[-1]:
            body.pop()
        while body and not body[0]:
            body.pop(0)
        return body, options, last + 1

    def _emit_text(self, tree: DocumentTree, body: str, start: int, end: int) -> None:
        tree.blocks.append(Block(kind="paragraph", text=self._clean(body), line=start, end_line=max(start, end)))
        self._emit_links(tree, body, start)

    @staticmethod
    def _clean(body: str) -> str:
        """Paragraph text for search: link and role markup reduced to its label."""
        clean = INLINE_LINK.sub(lambda m: m.group(1).strip() or m.group(2).strip(), body)
        clean = ROLE_LINK.sub(lambda m: m.group(2).split("<")[0].strip(), clean)
        clean = NAMED_REF.sub(lambda m: m.group(1), clean)
        return squash(clean.replace("``", "`"))

    @staticmethod
    def _emit_links(tree: DocumentTree, body: str, line: int) -> None:
        for m in INLINE_LINK.finditer(body):
            tree.blocks.append(Block(kind="link", text=m.group(1).strip(), target=m.group(2).strip(), line=line, end_line=line))
        for m in ROLE_LINK.finditer(body):
            role, inner = m.group(1), m.group(2)
            label = inner
            if "<" in inner and inner.endswith(">"):
                label, inner = inner.rsplit("<", 1)
                inner = inner.rstrip(">").strip()
            if role == "ref":
                tree.blocks.append(Block(kind="ref", text=label.strip(), target=inner.strip(), line=line, end_line=line,
                                         extra={"ref_kind": "label"}))
            else:
                tree.blocks.append(Block(kind="link", text=label.strip(), target=inner.strip(), line=line, end_line=line))
