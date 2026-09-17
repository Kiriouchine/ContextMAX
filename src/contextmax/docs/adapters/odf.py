# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`odf-v1`: OpenDocument text, presentation and drawing files (zipped `content.xml` or flat
`.fodt`/`.fodp`/`.fodg` XML) with the standard library. Headings from `text:h` outline levels,
lists, tables, links, footnotes, frames as figures; presentation pages as slides."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from contextmax.docs.adapters.common import split_number, squash
from contextmax.docs.adapters.container import local, open_package, parse_xml, read_xml
from contextmax.docs.adapters.pdf import sane_title
from contextmax.docs.base import Block, DocumentTree, ExtractionError

TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
PRES = "{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}"
XLINK = "{http://www.w3.org/1999/xlink}"
SVG = "{urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0}"
DC = "{http://purl.org/dc/elements/1.1/}"
META = "{urn:oasis:names:tc:opendocument:xmlns:meta:1.0}"
MAX_PARAGRAPHS = 200000


class OdfAdapter:
    id = "odf-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        if data.lstrip()[:5] == b"<?xml" or data.lstrip()[:1] == b"<":
            root = parse_xml(data, "flat OpenDocument")
            meta = root.find(f"{OFFICE}meta")
            body = root.find(f"{OFFICE}body")
        else:
            zf = open_package(data, "OpenDocument")
            root = read_xml(zf, "content.xml")
            if root is None:
                raise ExtractionError("content.xml missing")
            meta_root = read_xml(zf, "meta.xml")
            meta = meta_root.find(f"{OFFICE}meta") if meta_root is not None else None
            body = root.find(f"{OFFICE}body")
        if body is None:
            raise ExtractionError("OpenDocument has no office:body")
        self._meta(meta, tree)
        state = {"para": 0, "footnotes": 0}
        text_part = body.find(f"{OFFICE}text")
        pres_part = body.find(f"{OFFICE}presentation")
        draw_part = body.find(f"{OFFICE}drawing")
        if text_part is not None:
            tree.metadata["line_unit"] = "paragraph"
            self._walk(text_part, tree, state, 0, None)
        elif pres_part is not None or draw_part is not None:
            part = pres_part if pres_part is not None else draw_part
            tree.metadata["page_unit"] = "slide" if pres_part is not None else "page"
            pages = part.findall(f"{DRAW}page")
            tree.pages = len(pages)
            for n, page in enumerate(pages, start=1):
                label = f"{tree.metadata['page_unit']} {n}"
                tree.blocks.append(Block(kind="page", text=label, page=n, line=n, end_line=n))
                title = ""
                for frame in page.findall(f"{DRAW}frame"):
                    if frame.get(f"{PRES}class") == "title":
                        title = squash(" ".join(self._text_of(p) for p in frame.iter(f"{TEXT}p")))
                        break
                tree.blocks.append(Block(kind="heading", text=title or page.get(f"{DRAW}name") or f"Page {n}", level=1,
                                         page=n, line=n, end_line=n))
                for child in page:
                    if local(child.tag) == "frame" and child.get(f"{PRES}class") == "title":
                        continue
                    if local(child.tag) == "notes":
                        for p in child.iter(f"{TEXT}p"):
                            text = squash(self._text_of(p))
                            if text:
                                tree.blocks.append(Block(kind="paragraph", text=f"[notes] {text}", page=n, line=n, end_line=n))
                        continue
                    self._walk(child, tree, state, 0, n)
        else:
            raise ExtractionError("OpenDocument body has no text, presentation or drawing part (spreadsheets use sheet-v1)")
        if tree.title is None:
            first = next((b for b in tree.blocks if b.kind in ("title", "heading") and b.text), None)
            tree.title = first.text if first else key.rsplit("/", 1)[-1]
        if state["para"] >= MAX_PARAGRAPHS:
            tree.notes.append(f"TRUNCATED: first {MAX_PARAGRAPHS} paragraphs")
        return tree

    @staticmethod
    def _meta(meta: ET.Element | None, tree: DocumentTree) -> None:
        if meta is None:
            return
        for tag, field in ((f"{DC}title", "title"), (f"{DC}creator", "author"), (f"{DC}subject", "subject"),
                           (f"{DC}description", "description"), (f"{META}initial-creator", "initial_creator")):
            node = meta.find(tag)
            if node is not None and node.text and squash(node.text):
                tree.metadata[field] = squash(node.text)[:200]
        title = sane_title(tree.metadata.get("title", ""))
        if title:
            tree.title = title
            tree.metadata["title_source"] = "metadata"

    def _walk(self, node: ET.Element, tree: DocumentTree, state: dict[str, int], list_level: int, page: int | None) -> None:
        for child in node:
            if state["para"] >= MAX_PARAGRAPHS:
                return
            tag = local(child.tag)
            line = page if page is not None else state["para"] + 1
            if tag == "h":
                state["para"] += 1
                line = page if page is not None else state["para"]
                text = squash(self._text_of(child))
                if text:
                    level = int(child.get(f"{TEXT}outline-level") or 1)
                    number, clean = split_number(text)
                    tree.blocks.append(Block(kind="heading", text=clean, level=level, number=number, page=page, line=line, end_line=line))
                    self._inline(child, tree, line, page, state)
            elif tag == "p":
                state["para"] += 1
                line = page if page is not None else state["para"]
                text = squash(self._text_of(child))
                if text:
                    kind = "list_item" if list_level else "paragraph"
                    tree.blocks.append(Block(kind=kind, text=text, level=list_level, page=page, line=line, end_line=line))
                self._inline(child, tree, line, page, state)
            elif tag == "list":
                self._walk(child, tree, state, list_level + 1, page)
            elif tag == "list-item" or tag == "list-header":
                self._walk(child, tree, state, list_level, page)
            elif tag == "table":
                state["para"] += 1
                line = page if page is not None else state["para"]
                rows = []
                for tr in child.iter(f"{TABLE}table-row"):
                    rows.append([squash(" ".join(self._text_of(p) for p in tc.iter(f"{TEXT}p"))) for tc in tr.findall(f"{TABLE}table-cell")])
                tree.blocks.append(Block(kind="table", text=child.get(f"{TABLE}name") or "", rows=rows, page=page, line=line, end_line=line))
            elif tag == "frame":
                image = child.find(f"{DRAW}image")
                caption = squash(" ".join((c.text or "") for c in child if local(c.tag) in ("desc", "title")))
                if image is not None:
                    tree.blocks.append(Block(kind="figure", text=caption or child.get(f"{DRAW}name") or "",
                                             target=image.get(f"{XLINK}href"), page=page, line=line, end_line=line))
                self._walk(child, tree, state, list_level, page)
            elif tag in ("section", "text-box", "custom-shape", "g", "index-body", "table-of-content", "illustration-index",
                         "user-index", "alphabetical-index", "bibliography", "index-title"):
                if tag == "table-of-content":
                    tree.metadata["toc_field"] = True
                self._walk(child, tree, state, list_level, page)

    def _inline(self, node: ET.Element, tree: DocumentTree, line: int, page: int | None, state: dict[str, int]) -> None:
        for a in node.iter(f"{TEXT}a"):
            href = a.get(f"{XLINK}href")
            if href:
                tree.blocks.append(Block(kind="link", text=squash("".join(a.itertext())), target=href, page=page, line=line, end_line=line))
        for note in node.iter(f"{TEXT}note"):
            body = note.find(f"{TEXT}note-body")
            cite = note.find(f"{TEXT}note-citation")
            if body is not None:
                state["footnotes"] += 1
                label = (cite.text if cite is not None and cite.text else str(state["footnotes"])).strip()
                tree.blocks.append(Block(kind="footnote", text=squash(" ".join(self._text_of(p) for p in body.iter(f"{TEXT}p"))),
                                         target=label, page=page, line=line, end_line=line))
        for frame in node.iter(f"{DRAW}frame"):
            image = frame.find(f"{DRAW}image")
            if image is not None:
                caption = squash(" ".join((c.text or "") for c in frame if local(c.tag) in ("desc", "title")))
                tree.blocks.append(Block(kind="figure", text=caption or frame.get(f"{DRAW}name") or "",
                                         target=image.get(f"{XLINK}href"), page=page, line=line, end_line=line))

    def _text_of(self, node: ET.Element) -> str:
        parts: list[str] = []

        def visit(n: ET.Element) -> None:
            tag = local(n.tag)
            if tag == "note":  # footnote bodies are separate blocks
                if n.tail:
                    parts.append(n.tail)
                return
            if tag == "s":
                parts.append(" " * int(n.get(f"{TEXT}c") or 1))
            elif tag == "tab":
                parts.append("\t")
            elif tag == "line-break":
                parts.append(" ")
            elif tag in ("frame",):
                if n.tail:
                    parts.append(n.tail)
                return
            if n.text and tag not in ("s", "tab", "line-break"):
                parts.append(n.text)
            for c in n:
                visit(c)
                if c.tail and local(c.tag) not in ("note", "frame"):
                    parts.append(c.tail)

        visit(node)
        return "".join(parts)
