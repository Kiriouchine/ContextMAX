# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`html-v1`: headings, paragraphs, lists, tables, links, images and the title from HTML,
using the standard library parser. Scripts and styles are dropped entirely."""

from __future__ import annotations

from html.parser import HTMLParser

from contextmax.docs.adapters.common import decode, split_number, squash
from contextmax.docs.base import Block, DocumentTree

HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "li",
    "td",
    "th",
    "pre",
    "blockquote",
    "figcaption",
    "dd",
    "dt",
}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}


class _Parser(HTMLParser):
    def __init__(self, tree: DocumentTree) -> None:
        super().__init__(convert_charrefs=True)
        self.tree = tree
        self.skip_depth = 0
        self.stack: list[tuple[str, int]] = []
        self.buffer: list[str] = []
        self.buffer_line = 1
        self.in_title = False
        self.title_parts: list[str] = []
        self.table_rows: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.table_line = 0
        self.pre_depth = 0
        self.list_depth = 0
        self.href: str | None = None
        self.href_text: list[str] = []
        self.href_line = 0

    def line(self) -> int:
        return self.getpos()[0]

    def flush(self) -> None:
        body = (
            squash(" ".join(self.buffer))
            if not self.pre_depth
            else "\n".join(self.buffer).strip("\n")
        )
        self.buffer = []
        if not body:
            return
        heading = next((tag for tag, _ in reversed(self.stack) if tag in HEADINGS), None)
        if heading:
            number, clean = split_number(body)
            self.tree.blocks.append(
                Block(
                    kind="heading",
                    text=clean,
                    line=self.buffer_line,
                    end_line=self.line(),
                    level=HEADINGS[heading],
                    number=number,
                )
            )
            if self.tree.title is None and heading == "h1":
                self.tree.title = clean
        elif self.pre_depth:
            self.tree.blocks.append(
                Block(kind="code", text=body, line=self.buffer_line, end_line=self.line())
            )
        elif self.list_depth and any(tag == "li" for tag, _ in self.stack):
            self.tree.blocks.append(
                Block(
                    kind="list_item",
                    text=body,
                    line=self.buffer_line,
                    end_line=self.line(),
                    level=self.list_depth,
                )
            )
        else:
            self.tree.blocks.append(
                Block(kind="paragraph", text=body, line=self.buffer_line, end_line=self.line())
            )

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        attrs_d = dict(attrs)
        if tag == "title":
            self.in_title = True
        elif tag in HEADINGS or tag in BLOCK_TAGS or tag == "br":
            if tag != "br" or self.buffer:
                self.flush()
            self.buffer_line = self.line()
        if tag in ("ul", "ol"):
            self.list_depth += 1
        if tag == "pre":
            self.pre_depth += 1
        if tag == "table":
            self.flush()
            self.table_rows = []
            self.table_line = self.line()
        if tag == "tr" and self.table_rows is not None:
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []
        if tag == "a" and attrs_d.get("href"):
            self.href = attrs_d["href"]
            self.href_text = []
            self.href_line = self.line()
        if tag == "img":
            self.tree.blocks.append(
                Block(
                    kind="figure",
                    text=squash(attrs_d.get("alt") or ""),
                    line=self.line(),
                    end_line=self.line(),
                    target=attrs_d.get("src"),
                )
            )
        if tag not in ("br", "img", "hr", "meta", "link", "input"):
            self.stack.append((tag, self.line()))

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = False
            if self.tree.title is None:
                self.tree.title = squash(" ".join(self.title_parts)) or None
        if tag == "a" and self.href is not None:
            self.tree.blocks.append(
                Block(
                    kind="link",
                    text=squash(" ".join(self.href_text)),
                    line=self.href_line,
                    end_line=self.line(),
                    target=self.href,
                )
            )
            self.href = None
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(squash(" ".join(self.cell)))
            self.cell = None
        if tag == "tr" and self.row is not None and self.table_rows is not None:
            self.table_rows.append(self.row)
            self.row = None
        if tag == "table" and self.table_rows is not None:
            rows = self.table_rows
            self.tree.blocks.append(
                Block(
                    kind="table",
                    text="\n".join("\t".join(r) for r in rows),
                    line=self.table_line,
                    end_line=self.line(),
                    rows=rows,
                )
            )
            self.table_rows = None
        if tag in HEADINGS or tag in BLOCK_TAGS:
            self.flush()
        if tag in ("ul", "ol"):
            self.list_depth = max(0, self.list_depth - 1)
        if tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx][0] == tag:
                del self.stack[idx:]
                break

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.cell is not None:
            self.cell.append(data)
        if self.href is not None:
            self.href_text.append(data)
        if not self.buffer:
            self.buffer_line = self.line()
        self.buffer.append(data)


class HtmlAdapter:
    id = "html-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        tree = DocumentTree(
            key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism
        )
        parser = _Parser(tree)
        try:
            parser.feed(decode(data))
            parser.close()
        except Exception as exc:  # the stdlib parser is lenient; anything else is recorded
            tree.errors.append(f"html parse error: {exc.__class__.__name__}: {exc}")
        parser.flush()
        return tree
