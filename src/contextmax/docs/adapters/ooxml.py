# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`ooxml-v1`: Word (.docx) and PowerPoint (.pptx) packages with the standard library.

Word: paragraphs in document order, heading styles as headings (the style name decides, so
localised style ids still work), list paragraphs as list items, tables row per line,
hyperlinks, footnotes, comments, drawings as figures, the TOC field noted. Positions are
paragraph ordinals (`line_unit: paragraph`). PowerPoint: one section per slide with the title
placeholder as heading, body text, tables, pictures, hyperlinks and speaker notes; positions
are slide numbers (`page_unit: slide`)."""

from __future__ import annotations

import posixpath
import re
from typing import Any
from xml.etree import ElementTree as ET

from contextmax.docs.adapters.common import split_number, squash
from contextmax.docs.adapters.container import local, open_package, read_xml
from contextmax.docs.adapters.pdf import sane_title
from contextmax.docs.base import Block, DocumentTree, ExtractionError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DC = "{http://purl.org/dc/elements/1.1/}"
CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
HEADING_NAME = re.compile(r"^heading\s*(\d)$", re.I)
HEADING_ID = re.compile(r"^(?:Heading|berschrift|Titre|Ttulo)(\d)$", re.I)
TOC_STYLE = re.compile(r"^toc\s*\d", re.I)
MAX_SLIDES = 2000
MAX_PARAGRAPHS = 200000


class OoxmlAdapter:
    id = "ooxml-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        zf = open_package(data, "OOXML")
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        names = set(zf.namelist())
        self._core(zf, tree)
        if "word/document.xml" in names:
            self._docx(zf, tree)
        elif "ppt/presentation.xml" in names:
            self._pptx(zf, tree)
        else:
            raise ExtractionError("OOXML package is neither a Word document nor a presentation")
        if not tree.title:
            first = next((b for b in tree.blocks if b.kind in ("title", "heading") and b.text), None)
            tree.title = first.text if first else key.rsplit("/", 1)[-1]
        return tree

    # ----- shared -------------------------------------------------------------------------
    @staticmethod
    def _core(zf: Any, tree: DocumentTree) -> None:
        core = read_xml(zf, "docProps/core.xml")
        if core is None:
            return
        for tag, field in ((f"{DC}title", "title"), (f"{DC}creator", "author"), (f"{DC}subject", "subject"),
                           (f"{DC}description", "description"), (f"{CP}lastModifiedBy", "last_modified_by")):
            node = core.find(tag)
            if node is not None and node.text and squash(node.text):
                tree.metadata[field] = squash(node.text)[:200]
        title = sane_title(tree.metadata.get("title", ""))
        if title:
            tree.title = title
            tree.metadata["title_source"] = "metadata"

    @staticmethod
    def _rels(zf: Any, name: str) -> dict[str, tuple[str, bool, str]]:
        """rId -> (target, external, type)."""
        root = read_xml(zf, name)
        out: dict[str, tuple[str, bool, str]] = {}
        if root is None:
            return out
        for rel in root.iter(f"{REL}Relationship"):
            rid = rel.get("Id")
            if rid:
                out[rid] = (rel.get("Target", ""), rel.get("TargetMode") == "External", rel.get("Type", "").rsplit("/", 1)[-1])
        return out

    # ----- Word -----------------------------------------------------------------------------
    def _styles(self, zf: Any) -> dict[str, tuple[str, int | None]]:
        """styleId -> (name, heading level or None)."""
        root = read_xml(zf, "word/styles.xml")
        out: dict[str, tuple[str, int | None]] = {}
        if root is None:
            return out
        for style in root.iter(f"{W}style"):
            sid = style.get(f"{W}styleId") or ""
            name_node = style.find(f"{W}name")
            name = (name_node.get(f"{W}val") if name_node is not None else "") or ""
            level: int | None = None
            m = HEADING_NAME.match(name) or HEADING_ID.match(sid)
            if m:
                level = int(m.group(1))
            elif name.lower() == "title" or sid.lower() == "title":
                level = 0
            out[sid] = (name, level)
        return out

    def _docx(self, zf: Any, tree: DocumentTree) -> None:
        root = read_xml(zf, "word/document.xml")
        if root is None:
            raise ExtractionError("word/document.xml missing")
        body = root.find(f"{W}body")
        if body is None:
            raise ExtractionError("word/document.xml has no body")
        styles = self._styles(zf)
        rels = self._rels(zf, "word/_rels/document.xml.rels")
        footnotes = self._notes(zf, "word/footnotes.xml", f"{W}footnote")
        comments = self._notes(zf, "word/comments.xml", f"{W}comment")
        tree.metadata["line_unit"] = "paragraph"
        state = {"para": 0, "toc": False}
        self._walk_body(body, tree, styles, rels, footnotes, comments, state)
        if state["toc"]:
            tree.metadata["toc_field"] = True
        if state["para"] >= MAX_PARAGRAPHS:
            tree.notes.append(f"TRUNCATED: first {MAX_PARAGRAPHS} paragraphs")

    def _walk_body(self, node: ET.Element, tree: DocumentTree, styles, rels, footnotes, comments, state) -> None:
        for child in node:
            if state["para"] >= MAX_PARAGRAPHS:
                return
            tag = local(child.tag)
            if tag == "p":
                state["para"] += 1
                self._paragraph(child, tree, styles, rels, footnotes, comments, state)
            elif tag == "tbl":
                state["para"] += 1
                rows = []
                for tr in child.iter(f"{W}tr"):
                    cells = []
                    for tc in tr.findall(f"{W}tc"):
                        cells.append(squash(" ".join(self._runs_text(p, rels, None, None)[0] for p in tc.iter(f"{W}p"))))
                    rows.append(cells)
                tree.blocks.append(Block(kind="table", rows=rows, line=state["para"], end_line=state["para"]))
            elif tag in ("sdt", "sdtContent", "smartTag", "customXml", "ins", "moveTo"):
                inner = child.find(f"{W}sdtContent") if tag == "sdt" else child
                if inner is not None:
                    if tag == "sdt" and any("TOC" in (t.text or "") for t in child.iter(f"{W}instrText")):
                        state["toc"] = True
                    self._walk_body(inner, tree, styles, rels, footnotes, comments, state)

    def _paragraph(self, p: ET.Element, tree: DocumentTree, styles, rels, footnotes, comments, state) -> None:
        line = state["para"]
        ppr = p.find(f"{W}pPr")
        style_id = ""
        list_level: int | None = None
        if ppr is not None:
            ps = ppr.find(f"{W}pStyle")
            style_id = (ps.get(f"{W}val") if ps is not None else "") or ""
            num = ppr.find(f"{W}numPr")
            if num is not None:
                ilvl = num.find(f"{W}ilvl")
                list_level = int(ilvl.get(f"{W}val") or 0) + 1 if ilvl is not None else 1
        name, level = styles.get(style_id, (style_id, None))
        if any("TOC" in (t.text or "") for t in p.iter(f"{W}instrText")):
            state["toc"] = True
        text, links = self._runs_text(p, rels, footnotes, comments)
        text = squash(text)
        for target, label in links:
            tree.blocks.append(Block(kind="link", text=label, target=target, line=line, end_line=line))
        for drawing in p.iter(f"{WP}docPr"):
            caption = squash(drawing.get("descr") or drawing.get("title") or drawing.get("name") or "")
            tree.blocks.append(Block(kind="figure", text=caption, line=line, end_line=line))
        for ref in p.iter(f"{W}footnoteReference"):
            fid = ref.get(f"{W}id") or ""
            if fid in footnotes:
                tree.blocks.append(Block(kind="footnote", text=footnotes[fid], target=fid, line=line, end_line=line))
        for ref in p.iter(f"{W}commentRangeStart"):
            cid = ref.get(f"{W}id") or ""
            if cid in comments:
                tree.blocks.append(Block(kind="footnote", text=comments[cid], target=f"comment-{cid}", line=line, end_line=line,
                                         extra={"comment": True}))
        if not text:
            return
        if TOC_STYLE.match(name) or TOC_STYLE.match(style_id):
            state["toc"] = True
            tree.blocks.append(Block(kind="paragraph", text=text, line=line, end_line=line, extra={"toc_entry": True}))
            return
        if level == 0:
            if tree.title is None:
                tree.title = text
                tree.metadata["title_source"] = "title-style"
            tree.blocks.append(Block(kind="title", text=text, line=line, end_line=line))
        elif level:
            number, clean = split_number(text)
            tree.blocks.append(Block(kind="heading", text=clean, level=level, number=number, line=line, end_line=line))
        elif list_level:
            tree.blocks.append(Block(kind="list_item", text=text, level=list_level, line=line, end_line=line))
        else:
            tree.blocks.append(Block(kind="paragraph", text=text, line=line, end_line=line))

    def _runs_text(self, p: ET.Element, rels, footnotes, comments) -> tuple[str, list[tuple[str, str]]]:
        parts: list[str] = []
        links: list[tuple[str, str]] = []
        pending_url: str | None = None
        for node in p.iter():
            tag = local(node.tag)
            if tag == "t":
                parts.append(node.text or "")
            elif tag == "tab":
                parts.append("\t")
            elif tag in ("br", "cr"):
                parts.append(" ")
            elif tag == "hyperlink":
                rid = node.get(f"{R}id")
                anchor = node.get(f"{W}anchor")
                label = squash("".join(t.text or "" for t in node.iter(f"{W}t")))
                if rid and rid in rels:
                    links.append((rels[rid][0], label))
                elif anchor:
                    links.append((f"#{anchor}", label))
            elif tag == "instrText":
                m = re.search(r'HYPERLINK\s+"([^"]+)"', node.text or "")
                if m:
                    pending_url = m.group(1)
            elif tag == "fldChar" and node.get(f"{W}fldCharType") == "end" and pending_url:
                links.append((pending_url, pending_url))
                pending_url = None
        return "".join(parts), links

    @staticmethod
    def _notes(zf: Any, name: str, tag: str) -> dict[str, str]:
        root = read_xml(zf, name)
        out: dict[str, str] = {}
        if root is None:
            return out
        for note in root.iter(tag):
            nid = note.get(f"{W}id") or ""
            text = squash(" ".join(t.text or "" for t in note.iter(f"{W}t")))
            if nid and text and not nid.startswith("-"):
                out[nid] = text
        return out

    # ----- PowerPoint -------------------------------------------------------------------------
    def _pptx(self, zf: Any, tree: DocumentTree) -> None:
        pres = read_xml(zf, "ppt/presentation.xml")
        if pres is None:
            raise ExtractionError("ppt/presentation.xml missing")
        rels = self._rels(zf, "ppt/_rels/presentation.xml.rels")
        slide_targets = []
        for sld in pres.iter(f"{P}sldId"):
            rid = sld.get(f"{R}id")
            if rid in rels:
                slide_targets.append(posixpath.normpath(posixpath.join("ppt", rels[rid][0])))
        tree.metadata["page_unit"] = "slide"
        tree.pages = len(slide_targets)
        if len(slide_targets) > MAX_SLIDES:
            tree.notes.append(f"TRUNCATED: first {MAX_SLIDES} of {len(slide_targets)} slides")
        for n, path in enumerate(slide_targets[:MAX_SLIDES], start=1):
            slide = read_xml(zf, path)
            tree.blocks.append(Block(kind="page", text=f"slide {n}", page=n, line=n, end_line=n))
            if slide is None:
                tree.notes.append(f"slide {n}: {path} missing")
                continue
            slide_rels = self._rels(zf, posixpath.join(posixpath.dirname(path), "_rels", posixpath.basename(path) + ".rels"))
            title = ""
            body_blocks: list[Block] = []
            for sp in slide.iter():
                tag = local(sp.tag)
                if tag == "sp":
                    ph = next((x for x in sp.iter(f"{P}ph")), None)
                    ph_type = ph.get("type", "body") if ph is not None else ""
                    paras = self._drawing_paragraphs(sp)
                    if ph_type in ("title", "ctrTitle") and not title:
                        title = squash(" ".join(t for t, _ in paras))
                        continue
                    for text, lvl in paras:
                        if not text:
                            continue
                        kind = "list_item" if lvl > 0 else "paragraph"
                        body_blocks.append(Block(kind=kind, text=text, level=lvl if lvl > 0 else 0, page=n, line=n, end_line=n))
                elif tag == "graphicFrame":
                    tbl = next((x for x in sp.iter(f"{A}tbl")), None)
                    if tbl is not None:
                        rows = [[squash(" ".join(t.text or "" for t in tc.iter(f"{A}t"))) for tc in tr.findall(f"{A}tc")]
                                for tr in tbl.findall(f"{A}tr")]
                        body_blocks.append(Block(kind="table", rows=rows, page=n, line=n, end_line=n))
                elif tag == "pic":
                    descr = next((c.get("descr") or c.get("name") or "" for c in sp.iter(f"{P}cNvPr")), "")
                    body_blocks.append(Block(kind="figure", text=squash(descr), page=n, line=n, end_line=n))
            for hl in slide.iter(f"{A}hlinkClick"):
                rid = hl.get(f"{R}id")
                if rid and rid in slide_rels and slide_rels[rid][1]:
                    body_blocks.append(Block(kind="link", text=slide_rels[rid][0], target=slide_rels[rid][0], page=n, line=n, end_line=n))
            heading_extra: dict[str, Any] = {}
            if not title:
                # No title placeholder: a short first text line stands in, and says so.
                first_text = next((b for b in body_blocks if b.kind in ("paragraph", "list_item") and b.text), None)
                if first_text is not None and len(first_text.text.split()) <= 12 and sum(ch.isalpha() for ch in first_text.text) >= 3:
                    title = first_text.text
                    body_blocks.remove(first_text)
                    heading_extra = {"title_source": "first-text"}
            tree.blocks.append(Block(kind="heading", text=title or f"Slide {n}", level=1, page=n, line=n, end_line=n, extra=heading_extra))
            tree.blocks.extend(body_blocks)
            notes_rel = next((t for t, _, typ in slide_rels.values() if typ == "notesSlide"), None)
            if notes_rel:
                notes = read_xml(zf, posixpath.normpath(posixpath.join(posixpath.dirname(path), notes_rel)))
                if notes is not None:
                    for sp in notes.iter(f"{P}sp"):
                        ph = next((x for x in sp.iter(f"{P}ph")), None)
                        if ph is not None and ph.get("type") in ("sldNum", "sldImg"):
                            continue
                        for text, _ in self._drawing_paragraphs(sp):
                            if text:
                                tree.blocks.append(Block(kind="paragraph", text=f"[notes] {text}", page=n, line=n, end_line=n))
        if tree.title is None and slide_targets:
            first = next((b for b in tree.blocks if b.kind == "heading"), None)
            if first and not first.text.startswith("Slide "):
                tree.title = first.text
                tree.metadata["title_source"] = "first-slide"

    @staticmethod
    def _drawing_paragraphs(sp: ET.Element) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for para in sp.iter(f"{A}p"):
            ppr = para.find(f"{A}pPr")
            lvl = int(ppr.get("lvl") or 0) if ppr is not None else 0
            bullet = ppr is not None and (ppr.find(f"{A}buChar") is not None or ppr.find(f"{A}buAutoNum") is not None)
            text = squash("".join((t.text or "") if local(t.tag) == "t" else " " for t in para.iter() if local(t.tag) in ("t", "br")))
            out.append((text, lvl + 1 if (bullet or lvl > 0) else 0))
        return out
