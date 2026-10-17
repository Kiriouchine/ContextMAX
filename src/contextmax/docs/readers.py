"""Text out of one document: PDF, Word, RTF, plain text. Workbooks are read by sheets.py.

Every reader writes UTF-8 with LF line ends and answers with a small report,
{"ok": True, "method": ..., "pages": n or None, "needs_ocr": bool}. Nothing raises past
`extract()`: a failure becomes {"ok": False, "error": "..."}, so one bad file cannot stop a
build of thousands.
"""
from __future__ import annotations

import html
import os
import re
import zipfile
from contextlib import closing
from pathlib import Path

from contextmax import util

SCAN_CHARS_PER_PAGE = 30          # fewer characters than this per page: a scan, read again with OCR
_EXTENDED = "\\\\?\\"             # the prefix that lifts Windows' 260-character path limit
_CARRIAGE_RETURN = re.compile(r"\r\n?")


def win_path(path: str | os.PathLike) -> str:
    """An absolute path that Windows can open even past 260 characters."""
    full = os.path.abspath(str(path))
    if os.name != "nt" or len(full) <= 250 or full.startswith(_EXTENDED):
        return full
    if full.startswith("\\\\"):                  # \\server\share\... becomes \\?\UNC\server\share\...
        return _EXTENDED + "UNC" + full[1:]
    return _EXTENDED + full


def write_out(out_path: str | os.PathLike, text: str) -> str:
    text = _CARRIAGE_RETURN.sub("\n", text)
    target = Path(win_path(out_path))
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return text


def read_pdf(in_path: str, out_path: str) -> dict:
    import pypdfium2 as pdfium

    with closing(pdfium.PdfDocument(win_path(in_path))) as doc:
        pages = []
        for index in range(len(doc)):
            with closing(doc[index]) as page, closing(page.get_textpage()) as textpage:
                pages.append(textpage.get_text_range())
        try:
            title_field = (doc.get_metadata_dict() or {}).get("Title") or ""
        except Exception:  # noqa: BLE001 - the title field is optional
            title_field = ""
    pages = [_CARRIAGE_RETURN.sub("\n", p) for p in pages]
    text = write_out(out_path, "\n".join(pages))
    letters = len(text) - sum(1 for c in text if c.isspace())
    title, source = document_title(title_field, pages[0] if pages else "")
    return {"ok": True, "method": "pdfium", "pages": len(pages), "page_lines": page_starts(pages, 1),
            "needs_ocr": bool(pages) and letters / len(pages) < SCAN_CHARS_PER_PAGE,
            "title": title, "title_source": source}


def page_starts(pages: list[str], gap: int) -> list[int]:
    """The line each page starts on (counted from 1) in the pages' text joined by `gap` line ends: what a
    value's page is found by."""
    starts, line = [], 1
    for p in pages:
        starts.append(line)
        line += p.count("\n") + gap
    return starts


_NOT_A_TITLE = re.compile("|".join((
    r"\.(?:docx?|pdf|tex|dvi|djvu|pptx?|xlsx?)\b",       # a file name
    "^untitled", "^microsoft word", "^title$", r"^document\d*$", r"^slide \d", r"^page \d",
    r"[\\/]", "^[a-z]:",                                  # a path
)), re.I)


def document_title(title_field: str, first_page: str) -> tuple[str, str]:
    """The title a person would cite: the file's own title field when it holds a real title,
    else the first title-like line of the first page; empty when neither looks right."""
    field = " ".join((title_field or "").split())
    if 3 <= len(field.split()) <= 30 and not _NOT_A_TITLE.search(field):
        return field, "metadata"
    for raw in first_page.replace("\r", "\n").split("\n")[:25]:
        line = " ".join(raw.split())
        letters = sum(c.isalpha() for c in line)
        if (3 <= len(line.split()) <= 24 and line[:1].isupper() and not _NOT_A_TITLE.search(line)
                and letters >= 0.7 * len(line) and not line.endswith((".", ",", ";"))):
            return line, "first line"
    return "", ""


def _tag(name: str, empty: bool = False) -> str:
    """A regex for a WordprocessingML element: <w:name .../> when empty, else <w:name ...>.</w:name>."""
    return rf"<w:{name}\b[^>]*/>" if empty else rf"<w:{name}[ >].*?</w:{name}>|<w:{name}/>"


_PARAGRAPH = re.compile(_tag("p"), re.S)
_STYLE_REF = re.compile(r'<w:pStyle w:val="([^"]+)"')
_OUTLINE_LEVEL = re.compile(r'<w:outlineLvl w:val="(\d)"')
_TAB, _BREAK = re.compile(_tag("tab", True)), re.compile(_tag("br", True))
_ANY_TAG = re.compile(r"<[^>]+>")
_STYLE = re.compile(r'<w:style\b[^>]*w:styleId="([^"]+)"[^>]*>(.*?)</w:style>', re.S)
_STYLE_NAME = re.compile(r'<w:name w:val="([^"]+)"')


def read_docx(in_path: str, out_path: str) -> dict:
    """A .docx is a zip of XML. Paragraph ends and breaks become newlines, table cells tabs, and
    headings are marked with their outline level so the map can find the chapters."""
    with zipfile.ZipFile(win_path(in_path)) as z:
        names = set(z.namelist())

        def part(name: str) -> str:
            return z.read(name).decode("utf-8", "replace") if name in names else ""

        body = z.read("word/document.xml").decode("utf-8", "replace")      # required: a .docx without it is broken
        styles, props = part("word/styles.xml"), part("docProps/core.xml")
    found = re.search(r"<dc:title>(.*?)</dc:title>", props, flags=re.S)
    levels = _heading_levels(styles)
    lines = []
    for para in _PARAGRAPH.findall(body):
        style = _STYLE_REF.search(para)
        level = levels.get(style.group(1)) if style else None
        outline = _OUTLINE_LEVEL.search(para)
        if level is None and outline:
            level = int(outline.group(1)) + 1
        text = _BREAK.sub("\n", _TAB.sub("\t", para)).replace("</w:tc>", "\t")
        text = html.unescape(_ANY_TAG.sub("", text))
        lines.append("#" * min(level, 6) + " " + text.strip() if level and text.strip() else text)
    write_out(out_path, "\n".join(lines))
    opening = "\n".join(re.sub(r"^#+\s*", "", line) for line in lines[:40])
    title, source = document_title(html.unescape(found.group(1)) if found else "", opening)
    return {"ok": True, "method": "docx-zip", "pages": None, "needs_ocr": False, "title": title,
            "title_source": source}


def _heading_levels(styles_xml: str) -> dict[str, int]:
    """Style id -> heading level, from the style's name ("heading 2") or its outline level."""
    levels = {}
    for m in _STYLE.finditer(styles_xml):
        style_id, inner = m.group(1), m.group(2)
        named = _STYLE_NAME.search(inner)
        name = (named.group(1) if named else style_id).lower()
        numbered = re.match(r"heading\s*(\d)", name)
        outline = _OUTLINE_LEVEL.search(inner)
        if numbered:
            levels[style_id] = int(numbered.group(1))
        elif outline and name != "normal":
            levels[style_id] = int(outline.group(1)) + 1
    return levels


def read_plain(in_path: str, out_path: str) -> dict:
    with open(win_path(in_path), "rb") as fh:
        write_out(out_path, util.decode(fh.read()))
    return {"ok": True, "method": "passthrough", "pages": None, "needs_ocr": False}


def read_rtf(in_path: str, out_path: str) -> dict:
    """RTF without Word: control words out, text, breaks and special characters kept."""
    with open(win_path(in_path), "rb") as fh:
        write_out(out_path, rtf_text(fh.read().decode("latin-1")))
    return {"ok": True, "method": "rtf-text", "pages": None, "needs_ocr": False}


# Destinations whose content is never text of the document.
_RTF_HIDDEN = frozenset("""
    colorschememapping colortbl datastore fonttbl generator info latentstyles listoverridetable listtable
    object pict rsidtbl stylesheet themedata xmlnstbl
""".split())
# Control words that stand for one character.
_RTF_CHARACTERS = {"par": "\n", "line": "\n", "row": "\n", "sect": "\n", "page": "\n", "tab": "\t", "cell": "\t",
                   "emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022", "lquote": "\u2018", "rquote": "\u2019",
                   "ldblquote": "\u201c", "rdblquote": "\u201d", "emspace": " ", "enspace": " ", "qmspace": " "}
_RTF_SYMBOLS = {"{": "{", "}": "}", "\\": "\\", "~": "\u00a0", "_": "\u2011"}
_RTF_CONTROL = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)")


def _skip_fallback(rtf: str, i: int, count: int) -> int:
    """After \\uN come `count` stand-in characters for readers without Unicode; step over them.
    A stand-in is one plain character or one \\'hh escape."""
    for _ in range(count):
        if rtf.startswith("\\'", i) and len(rtf) >= i + 4:
            i += 4
        elif i < len(rtf) and rtf[i] not in "\\{}":
            i += 1
        else:
            break
    return i


def rtf_text(rtf: str) -> str:
    out: list[str] = []
    stack: list[tuple[bool, int]] = []
    hidden, fallback = False, 1             # \ucN sets how many stand-ins follow each \uN (default 1)
    i, n = 0, len(rtf)
    while i < n:
        c = rtf[i]
        if c == "{":
            stack.append((hidden, fallback))
            i += 1
            hidden = hidden or rtf.startswith("\\*", i)
        elif c == "}":
            hidden, fallback = stack.pop() if stack else (False, 1)
            i += 1
        elif c == "\\":
            m = _RTF_CONTROL.match(rtf, i)
            if not m:
                i += 1
                continue
            i = m.end()
            word, number, hex_code, symbol = m.groups()
            if word == "uc" and number:
                fallback = max(0, int(number))
            elif word in _RTF_HIDDEN:
                hidden = True
            elif hidden:
                continue
            elif word == "u" and number:
                out.append(chr(int(number) % 65536))
                i = _skip_fallback(rtf, i, fallback)
            elif word in _RTF_CHARACTERS:
                out.append(_RTF_CHARACTERS[word])
            elif hex_code:
                out.append(bytes([int(hex_code, 16)]).decode("cp1252", "replace"))
            elif symbol in _RTF_SYMBOLS:
                out.append(_RTF_SYMBOLS[symbol])
        else:
            if not hidden and c not in "\r\n":
                out.append(c)
            i += 1
    return "".join(out)


_READERS = {".pdf": read_pdf, ".docx": read_docx, ".docm": read_docx, ".txt": read_plain, ".md": read_plain,
            ".rst": read_plain, ".log": read_plain, ".rtf": read_rtf}


def extract(in_path: str, out_path: str) -> dict:
    ext = os.path.splitext(in_path)[1].lower()
    reader = _READERS.get(ext)
    if reader is None:
        return {"ok": False, "error": f"no reader for {ext}"}
    try:
        return reader(in_path, out_path)
    except Exception as exc:  # noqa: BLE001 - one bad file must never stop the batch
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
