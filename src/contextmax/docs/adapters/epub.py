# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`epub-v1`: chapters in spine order, each read through the HTML adapter; positions are
chapter numbers (`page_unit: chapter`). Internal links between chapters are kept as
cross-references; only external URLs become link references."""

from __future__ import annotations

import posixpath

from contextmax.docs.adapters.common import squash
from contextmax.docs.adapters.container import open_package, read_member, read_xml
from contextmax.docs.adapters.html import HtmlAdapter
from contextmax.docs.base import Block, DocumentTree, ExtractionError

CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"
MAX_CHAPTERS = 2000


class EpubAdapter:
    id = "epub-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        zf = open_package(data, "EPUB")
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        container = read_xml(zf, "META-INF/container.xml")
        if container is None:
            raise ExtractionError("META-INF/container.xml missing")
        rootfile = next((r.get("full-path") for r in container.iter(f"{CONTAINER}rootfile") if r.get("full-path")), None)
        if not rootfile:
            raise ExtractionError("container.xml names no rootfile")
        opf = read_xml(zf, rootfile)
        if opf is None:
            raise ExtractionError(f"{rootfile} missing")
        base = posixpath.dirname(rootfile)
        for tag, field in ((f"{DC}title", "title"), (f"{DC}creator", "author"), (f"{DC}language", "language"),
                           (f"{DC}publisher", "publisher"), (f"{DC}identifier", "identifier")):
            node = opf.find(f".//{tag}")
            if node is not None and node.text and squash(node.text):
                tree.metadata[field] = squash(node.text)[:200]
        if tree.metadata.get("title"):
            tree.title = tree.metadata["title"]
            tree.metadata["title_source"] = "metadata"
        manifest = {item.get("id"): (item.get("href", ""), item.get("media-type", "")) for item in opf.iter(f"{OPF}item")}
        spine = [ref.get("idref") for ref in opf.iter(f"{OPF}itemref")]
        chapters = [manifest[i] for i in spine if i in manifest]
        tree.metadata["page_unit"] = "chapter"
        tree.pages = len(chapters)
        if len(chapters) > MAX_CHAPTERS:
            tree.notes.append(f"TRUNCATED: first {MAX_CHAPTERS} of {len(chapters)} chapters")
        html = HtmlAdapter()
        for n, (href, media) in enumerate(chapters[:MAX_CHAPTERS], start=1):
            path = posixpath.normpath(posixpath.join(base, href)) if base else href
            tree.blocks.append(Block(kind="page", text=f"chapter {n}", page=n, line=n, end_line=n))
            content = read_member(zf, path)
            if content is None:
                tree.notes.append(f"chapter {n}: {path} missing")
                continue
            if "html" not in media and not path.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            sub = html.extract(f"{key}!{path}", content)
            chapter_title = sub.title or next((b.text for b in sub.blocks if b.kind == "heading"), "") or f"Chapter {n}"
            tree.blocks.append(Block(kind="heading", text=chapter_title, level=1, page=n, line=n, end_line=n))
            skipped_first = False
            for block in sub.blocks:
                if block.kind == "title":
                    continue
                if block.kind == "heading":
                    if not skipped_first and block.text == chapter_title:
                        skipped_first = True
                        continue
                    block.level = block.level + 1
                if block.kind == "link" and block.target and not block.target.lower().startswith(("http://", "https://", "mailto:")):
                    block.kind = "ref"
                    block.extra = {"ref_kind": "label", "internal": True}
                    block.target = block.target.split("#")[-1] if "#" in block.target else block.target
                block.page = n
                block.line = block.end_line = n
                tree.blocks.append(block)
        if tree.title is None:
            first = next((b for b in tree.blocks if b.kind == "heading"), None)
            tree.title = first.text if first else key.rsplit("/", 1)[-1]
        return tree
