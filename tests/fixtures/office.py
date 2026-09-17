# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Synthetic container documents (built in-process, byte-stable) shared by the corpus and the
container adapter tests: Word, PowerPoint, OpenDocument text and presentation, EPUB, RTF,
images and a genuine legacy .doc produced once by LibreOffice."""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path


def zipped(members: dict[str, bytes]) -> bytes:
    """A zip with fixed timestamps so the bytes never change between runs or machines."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return buf.getvalue()


W = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
RELS_NS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
REL_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
CORE = (
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Bench Report</dc:title><dc:creator>Me</dc:creator>'
    "</cp:coreProperties>"
)

DOCX = zipped(
    {
        "[Content_Types].xml": b"<Types/>",
        "docProps/core.xml": CORE.encode(),
        "word/styles.xml": (
            f'<w:styles {W}><w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
            '<w:style w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>'
            '<w:style w:styleId="TOC1"><w:name w:val="toc 1"/></w:style></w:styles>'
        ).encode(),
        "word/_rels/document.xml.rels": (
            f'<Relationships {RELS_NS}><Relationship Id="rId1" Type="{REL_HYPERLINK}" Target="https://example.org/x" '
            f'TargetMode="External"/><Relationship Id="rId2" Type="{REL_HYPERLINK}" Target="spec.md" '
            'TargetMode="External"/></Relationships>'
        ).encode(),
        "word/footnotes.xml": (
            f'<w:footnotes {W}><w:footnote w:id="1"><w:p><w:r><w:t>A footnote.</w:t></w:r></w:p></w:footnote></w:footnotes>'
        ).encode(),
        "word/document.xml": (
            f"<w:document {W}><w:body>"
            '<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:r><w:t>1 Scope 3</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>1 Scope</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">The servo shall hold </w:t></w:r><w:r><w:t>2.0 deg</w:t></w:r>'
            '<w:r><w:footnoteReference w:id="1"/></w:r><w:r><w:t>.</w:t></w:r></w:p>'
            '<w:p><w:hyperlink r:id="rId1"><w:r><w:t>example</w:t></w:r></w:hyperlink><w:r><w:t xml:space="preserve"> and </w:t></w:r>'
            '<w:hyperlink r:id="rId2"><w:r><w:t>the spec</w:t></w:r></w:hyperlink></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>1.1 Limits</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>first item</w:t></w:r></w:p>'
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>label</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>value</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>error</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>2.0</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
            "</w:body></w:document>"
        ).encode(),
    }
)

P = (
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
REL_SLIDE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
REL_NOTES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"

PPTX = zipped(
    {
        "docProps/core.xml": (
            b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            b'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Slide 1</dc:title></cp:coreProperties>'
        ),
        "ppt/presentation.xml": (
            f'<p:presentation {P}><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/>'
            "</p:sldIdLst></p:presentation>"
        ).encode(),
        "ppt/_rels/presentation.xml.rels": (
            f'<Relationships {RELS_NS}><Relationship Id="rId2" Type="{REL_SLIDE}" Target="slides/slide1.xml"/>'
            f'<Relationship Id="rId3" Type="{REL_SLIDE}" Target="slides/slide2.xml"/></Relationships>'
        ).encode(),
        "ppt/slides/slide1.xml": (
            f'<p:sld {P}><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2" name="Title 1"/><p:nvPr><p:ph type="ctrTitle"/>'
            "</p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>Gain Scheduling</a:t></a:r></a:p></p:txBody></p:sp>"
            '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body"/><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody>'
            '<a:p><a:pPr lvl="0"><a:buChar char="-"/></a:pPr><a:r><a:t>point one</a:t></a:r></a:p>'
            '<a:p><a:pPr lvl="1"/><a:r><a:t>sub point</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
        ).encode(),
        "ppt/slides/_rels/slide1.xml.rels": (
            f'<Relationships {RELS_NS}><Relationship Id="rId1" Type="{REL_NOTES}" Target="../notesSlides/notesSlide1.xml"/>'
            "</Relationships>"
        ).encode(),
        "ppt/notesSlides/notesSlide1.xml": (
            f'<p:notes {P}><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes"/><p:nvPr><p:ph type="body"/>'
            "</p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>Say hello.</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>"
        ).encode(),
        "ppt/slides/slide2.xml": (
            f'<p:sld {P}><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2" name="Text 1"/><p:nvPr/></p:nvSpPr><p:txBody>'
            "<a:p><a:r><a:t>Results</a:t></a:r></a:p><a:p><a:r><a:t>Everything passed, see run_all.m.</a:t></a:r></a:p></p:txBody></p:sp>"
            "<p:graphicFrame><a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>a</a:t></a:r></a:p></a:txBody></a:tc>"
            "<a:tc><a:txBody><a:p><a:r><a:t>b</a:t></a:r></a:p></a:txBody></a:tc></a:tr></a:tbl></p:graphicFrame>"
            '<p:pic><p:nvPicPr><p:cNvPr id="5" name="Picture" descr="bench photo"/></p:nvPicPr></p:pic>'
            "</p:spTree></p:cSld></p:sld>"
        ).encode(),
    }
)

ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)

ODT = zipped(
    {
        "mimetype": b"application/vnd.oasis.opendocument.text",
        "meta.xml": (
            b'<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            b'xmlns:dc="http://purl.org/dc/elements/1.1/"><office:meta><dc:title>Bench Notes (ODT)</dc:title>'
            b"</office:meta></office:document-meta>"
        ),
        "content.xml": (
            f"<office:document-content {ODF_NS}><office:body><office:text>"
            '<text:h text:outline-level="1">1 Intro</text:h>'
            '<text:p>Hello <text:a xlink:href="https://example.org/odt">site</text:a> world.'
            '<text:note text:note-class="footnote"><text:note-citation>1</text:note-citation>'
            "<text:note-body><text:p>Foot text.</text:p></text:note-body></text:note></text:p>"
            "<text:list><text:list-item><text:p>item a</text:p></text:list-item></text:list>"
            '<table:table table:name="T1"><table:table-row><table:table-cell><text:p>x</text:p></table:table-cell>'
            "<table:table-cell><text:p>y</text:p></table:table-cell></table:table-row></table:table>"
            "</office:text></office:body></office:document-content>"
        ).encode(),
    }
)

ODP = zipped(
    {
        "mimetype": b"application/vnd.oasis.opendocument.presentation",
        "content.xml": (
            f"<office:document-content {ODF_NS}><office:body><office:presentation>"
            '<draw:page draw:name="page1"><draw:frame presentation:class="title"><draw:text-box><text:p>Slide One</text:p>'
            '</draw:text-box></draw:frame><draw:frame presentation:class="outline"><draw:text-box><text:list>'
            "<text:list-item><text:p>bullet</text:p></text:list-item></text:list></draw:text-box></draw:frame>"
            "<presentation:notes><draw:frame><draw:text-box><text:p>note text</text:p></draw:text-box></draw:frame>"
            "</presentation:notes></draw:page></office:presentation></office:body></office:document-content>"
        ).encode(),
    }
)

EPUB = zipped(
    {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": (
            b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            b'<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
        ),
        "OEBPS/content.opf": (
            b'<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>'
            b"<dc:title>Little Book</dc:title><dc:creator>Me</dc:creator></metadata><manifest>"
            b'<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
            b'<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/></manifest>'
            b'<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>'
        ),
        "OEBPS/ch1.xhtml": (
            b"<html><head><title>One</title></head><body><h1>One</h1><p>First chapter with "
            b'<a href="ch2.xhtml#s2">a link</a> and <a href="https://example.org/epub">site</a>.</p>'
            b"<h2>Part</h2><p>More.</p></body></html>"
        ),
        "OEBPS/ch2.xhtml": b"<html><body><h1>Two</h1><p>Second.</p></body></html>",
    }
)

RTF = (
    rb"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0 Times;}}"
    rb"{\stylesheet{\s0 Normal;}{\s1\b heading 1;}{\s2 heading 2;}}"
    rb"\pard\s1\b 1 Introduction\b0\par" + b"\n"
    rb"\pard\s0 Plain text with \'e9 accent and " + bytes([92]) + rb"u8364? euro.\par" + b"\n"
    rb"\pard\b Bold Heading\b0\par" + b"\n"
    rb'{\field{\*\fldinst HYPERLINK "https://example.org/rtf"}{\fldrslt link}}\par' + b"\n"
    rb"\trowd\cellx1000\cellx2000 a\cell b\cell\row" + b"\n"
    rb"{\*\generator Foo}\pard Last paragraph mentions run_all.m.\par}"
)

PNG = (
    b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (640).to_bytes(4, "big") + (480).to_bytes(4, "big")
    + b"\x08\x02\x00\x00\x00"
)
GIF = b"GIF89a" + (12).to_bytes(2, "little") + (7).to_bytes(2, "little") + b"\x00\x00\x00"
BMP = b"BM" + bytes(16) + (320).to_bytes(4, "little") + (200).to_bytes(4, "little")
JPEG = b"\xff\xd8" + b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + bytes(9) + b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + (
    (240).to_bytes(2, "big") + (300).to_bytes(2, "big")
) + bytes(10)


def legacy_doc() -> bytes:
    """A genuine Word 97 .doc (two headings, one paragraph) converted once by LibreOffice and
    stored base64-encoded next to this module."""
    return base64.b64decode((Path(__file__).parent / "report_doc.b64").read_text(encoding="ascii"))


ODS = zipped(
    {
        "mimetype": b"application/vnd.oasis.opendocument.spreadsheet",
        "content.xml": (
            f"<office:document-content {ODF_NS}><office:body><office:spreadsheet>"
            '<table:table table:name="Params"><table:table-row>'
            '<table:table-cell office:value-type="string"><text:p>label</text:p></table:table-cell>'
            '<table:table-cell office:value-type="string"><text:p>value</text:p></table:table-cell>'
            '<table:table-cell office:value-type="string"><text:p>unit</text:p></table:table-cell>'
            "</table:table-row><table:table-row>"
            '<table:table-cell office:value-type="string"><text:p>servo error</text:p></table:table-cell>'
            '<table:table-cell office:value-type="float" office:value="2"><text:p>2</text:p></table:table-cell>'
            '<table:table-cell office:value-type="string"><text:p>deg</text:p></table:table-cell>'
            "</table:table-row><table:table-row>"
            '<table:table-cell office:value-type="string"><text:p>doubled</text:p></table:table-cell>'
            '<table:table-cell table:formula="of:=[.B2]*2" office:value-type="float" office:value="4"><text:p>4</text:p></table:table-cell>'
            '<table:table-cell table:number-columns-repeated="3"/>'
            "</table:table-row></table:table></office:spreadsheet></office:body></office:document-content>"
        ).encode(),
    }
)


def gains_xlsx() -> bytes:
    """A workbook made once with openpyxl: labels, units, a formula, a hidden row, two sheets."""
    return base64.b64decode((Path(__file__).parent / "gains_xlsx.b64").read_text(encoding="ascii"))


def book_xls() -> bytes:
    """A legacy Excel 97 workbook converted once by LibreOffice from a three-row CSV."""
    return base64.b64decode((Path(__file__).parent / "book_xls.b64").read_text(encoding="ascii"))
