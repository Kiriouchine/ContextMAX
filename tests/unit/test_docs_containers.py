# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Phase 3 session 2: OOXML, OpenDocument, EPUB, RTF, images, legacy Office and the zip guards."""

from __future__ import annotations

import io
import zipfile

import pytest

from contextmax.docs import structure as structure_module
from contextmax.docs.adapters import container
from contextmax.docs.adapters.epub import EpubAdapter
from contextmax.docs.adapters.image import ImageAdapter, dimensions
from contextmax.docs.adapters.legacy_office import LegacyOfficeAdapter, find_converter
from contextmax.docs.adapters.odf import OdfAdapter
from contextmax.docs.adapters.ooxml import OoxmlAdapter
from contextmax.docs.adapters.rtf import RtfAdapter
from contextmax.docs.base import ExtractionError
from contextmax.docs.run import section_cite
from fixtures import office


def kinds(tree, kind):
    return [b for b in tree.blocks if b.kind == kind]


# ----- Word ---------------------------------------------------------------------------------------
def test_docx_headings_links_footnotes_tables_and_paragraph_cites():
    tree = OoxmlAdapter().extract("docs/report.docx", office.DOCX)
    assert tree.title == "Bench Report" and tree.metadata["title_source"] == "metadata"
    assert tree.metadata["line_unit"] == "paragraph" and tree.metadata["toc_field"] is True
    assert [(h.level, h.number, h.text, h.line) for h in kinds(tree, "heading")] == [(1, "1", "Scope", 2), (2, "1.1", "Limits", 5)]
    toc_entries = [b for b in kinds(tree, "paragraph") if b.extra.get("toc_entry")]
    assert [b.text for b in toc_entries] == ["1 Scope 3"]
    assert "The servo shall hold 2.0 deg." in [b.text for b in kinds(tree, "paragraph")]
    assert kinds(tree, "footnote")[0].text == "A footnote."
    assert {b.target: b.text for b in kinds(tree, "link")} == {"https://example.org/x": "example", "spec.md": "the spec"}
    assert kinds(tree, "list_item")[0].text == "first item"
    assert kinds(tree, "table")[0].rows == [["label", "value"], ["error", "2.0"]]
    structure = structure_module.build(tree, "docs/report.docx")
    assert [s.id for s in structure.sections] == ["doc:docs/report.docx#1", "doc:docs/report.docx#1.1"]
    assert section_cite("docs/report.docx", structure.sections[0], "page", "paragraph") == "docs/report.docx ¶2-7 §1"  # section 1 spans its subsection and the table


# ----- PowerPoint ---------------------------------------------------------------------------------
def test_pptx_slides_titles_notes_and_slide_cites():
    tree = OoxmlAdapter().extract("docs/deck.pptx", office.PPTX)
    assert tree.title == "Gain Scheduling" and tree.metadata["title_source"] == "first-slide"  # "Slide 1" metadata rejected
    assert tree.pages == 2 and tree.metadata["page_unit"] == "slide"
    heads = kinds(tree, "heading")
    assert [(h.text, h.page) for h in heads] == [("Gain Scheduling", 1), ("Results", 2)]
    assert heads[1].extra == {"title_source": "first-text"}
    assert [(b.level, b.text) for b in kinds(tree, "list_item")] == [(1, "point one"), (2, "sub point")]
    assert "[notes] Say hello." in [b.text for b in kinds(tree, "paragraph")]
    assert kinds(tree, "table")[0].rows == [["a", "b"]] and kinds(tree, "figure")[0].text == "bench photo"
    structure = structure_module.build(tree, "docs/deck.pptx")
    assert section_cite("docs/deck.pptx", structure.sections[1], "slide") == "docs/deck.pptx slide 2 §results"


# ----- OpenDocument -------------------------------------------------------------------------------
def test_odt_and_odp():
    tree = OdfAdapter().extract("docs/notes.odt", office.ODT)
    assert tree.title == "Bench Notes (ODT)"
    assert [(h.level, h.number, h.text) for h in kinds(tree, "heading")] == [(1, "1", "Intro")]
    assert kinds(tree, "paragraph")[0].text == "Hello site world."  # footnote body kept apart
    assert kinds(tree, "footnote")[0].text == "Foot text." and kinds(tree, "link")[0].target == "https://example.org/odt"
    assert kinds(tree, "list_item")[0].text == "item a" and kinds(tree, "table")[0].rows == [["x", "y"]]
    deck = OdfAdapter().extract("docs/talk.odp", office.ODP)
    assert deck.metadata["page_unit"] == "slide" and deck.pages == 1 and deck.title == "Slide One"
    assert [b.text for b in kinds(deck, "list_item")] == ["bullet"]
    assert "[notes] note text" in [b.text for b in kinds(deck, "paragraph")]
    flat = OdfAdapter().extract("docs/flat.fodt", zipfile.ZipFile(io.BytesIO(office.ODT)).read("content.xml"))
    assert kinds(flat, "heading")[0].text == "Intro"


# ----- EPUB ---------------------------------------------------------------------------------------
def test_epub_chapters_in_spine_order():
    tree = EpubAdapter().extract("docs/book.epub", office.EPUB)
    assert tree.title == "Little Book" and tree.pages == 2 and tree.metadata["page_unit"] == "chapter"
    assert [(h.level, h.text, h.page) for h in kinds(tree, "heading")] == [(1, "One", 1), (3, "Part", 1), (1, "Two", 2)]
    internal = kinds(tree, "ref")[0]
    assert internal.target == "s2" and internal.extra["internal"] is True
    assert kinds(tree, "link")[0].target == "https://example.org/epub"
    structure = structure_module.build(tree, "docs/book.epub")
    assert section_cite("docs/book.epub", structure.sections[-1], "chapter") == "docs/book.epub chapter 2 §two"


# ----- RTF ----------------------------------------------------------------------------------------
def test_rtf_styles_escapes_fields_and_tables():
    tree = RtfAdapter().extract("docs/memo.rtf", office.RTF)
    assert tree.title == "Introduction"
    heads = kinds(tree, "heading")
    assert [(h.level, h.number, h.text) for h in heads] == [(1, "1", "Introduction"), (1, None, "Bold Heading")]
    assert heads[1].extra == {"bold_heading": True}
    paras = [b.text for b in kinds(tree, "paragraph")]
    assert "Plain text with é accent and € euro." in paras
    assert kinds(tree, "link")[0].target == "https://example.org/rtf"
    assert kinds(tree, "table")[0].rows == [["a", "b"]]
    with pytest.raises(ExtractionError):
        RtfAdapter().extract("x.rtf", b"not rtf")


# ----- Images -------------------------------------------------------------------------------------
def test_image_dimensions_and_catalog_document():
    assert dimensions(office.PNG) == ("png", 640, 480)
    assert dimensions(office.GIF) == ("gif", 12, 7)
    assert dimensions(office.BMP) == ("bmp", 320, 200)
    assert dimensions(office.JPEG) == ("jpeg", 300, 240)
    assert dimensions(b"nonsense") is None
    tree = ImageAdapter().extract("bin/photo.png", office.PNG)
    assert tree.metadata["width"] == 640 and tree.metadata["image_format"] == "png" and tree.blocks == []
    assert any("no OCR" in n for n in tree.notes)
    with pytest.raises(ExtractionError):
        ImageAdapter().extract("x.png", b"nonsense")


# ----- Zip guards ---------------------------------------------------------------------------------
def test_zip_guards_refuse_password_bombs_and_entities():
    encrypted = bytearray(office.zipped({"word/document.xml": b"<x/>"}))
    local = encrypted.find(b"PK\x03\x04")
    central = encrypted.find(b"PK\x01\x02")
    encrypted[local + 6] |= 0x1  # general purpose bit 0: encrypted (local header)
    encrypted[central + 8] |= 0x1  # and in the central directory
    with pytest.raises(ExtractionError, match="password"):
        container.open_package(bytes(encrypted), "OOXML")
    bomb = office.zipped(
        {"word/document.xml": b"\0" * (container.RATIO_CHECK_FROM + 1)}, compress=zipfile.ZIP_DEFLATED
    )
    with pytest.raises(ExtractionError, match="zip bomb"):
        container.open_package(bomb, "OOXML")
    entity = office.zipped({"word/document.xml": b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>'})
    with pytest.raises(ExtractionError, match="entities"):
        OoxmlAdapter().extract("x.docx", entity)
    with pytest.raises(ExtractionError, match="not a valid"):
        container.open_package(b"PK\x03\x04garbage", "OOXML")


# ----- Legacy Office ------------------------------------------------------------------------------
def test_legacy_office_is_unavailable_under_isolation():
    find_converter.cache_clear()
    ok, reason = LegacyOfficeAdapter().available()
    assert ok is False and "LibreOffice" in reason
    with pytest.raises(ExtractionError, match="converter"):
        LegacyOfficeAdapter().extract("docs/legacy.doc", office.legacy_doc())
    find_converter.cache_clear()


def test_legacy_doc_through_libreoffice_when_installed(monkeypatch):
    monkeypatch.delenv("CONTEXTMAX_NO_OPTIONAL_READERS", raising=False)
    find_converter.cache_clear()
    try:
        if find_converter() is None:
            pytest.skip("LibreOffice (soffice) not installed")
        tree = LegacyOfficeAdapter().extract("docs/legacy.doc", office.legacy_doc())
    finally:
        find_converter.cache_clear()
    assert tree.adapter == "legacy-office-v1" and tree.determinism == "environment-bound"
    assert tree.adapter_version.startswith("LibreOffice")
    # Converter versions differ between machines, so require the headings, not the whole list.
    headings = [(h.number, h.text) for h in kinds(tree, "heading")]
    assert ("1", "Scope") in headings and ("1.1", "Limits") in headings
    assert any("converted from .doc" in n for n in tree.notes)
