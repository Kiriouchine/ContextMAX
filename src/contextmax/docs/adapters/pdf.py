# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`pdf-v1`: text per page, bookmarks as the table of contents, link annotations, scan detection.

Version-bound: the extracted text depends on the installed pypdf version, which is recorded on
every document. Scanned pages are detected (fewer than SCAN_CHARS_PER_PAGE characters on
average) and flagged; nothing is OCR-ed. When a PDF has no bookmarks, headings are derived from
numbered or all-capital lines and the document says so (`toc_source: derived`).
"""

from __future__ import annotations

import io
import logging
import re
import warnings
from importlib import metadata
from typing import Any

from contextmax.docs.adapters.common import split_number, squash
from contextmax.docs.base import Block, DocumentTree, ExtractionError

SCAN_CHARS_PER_PAGE = 60
MAX_PAGES = 5000
MAX_NOTES = 3
NUMBERED_HEADING = re.compile(
    r"^(?:(?:\d+\.)*\d+|[A-Z]\.\d+(?:\.\d+)*|Chapter\s+\d+|Appendix\s+[A-Z]|[IVX]+\.)\s+[A-Za-z(][^\n]{1,90}$"
)
KEYWORD_HEADINGS = {
    "abstract", "summary", "contents", "table of contents", "introduction", "conclusion", "conclusions",
    "references", "bibliography", "literature", "works cited", "acknowledgements", "acknowledgments",
    "appendix", "appendices", "nomenclature", "glossary", "list of figures", "list of tables", "preface",
}
_URL = re.compile(r"https?://[^\s<>()\"']+[^\s<>()\"'.,;:]")
_TITLE_PREFIX = re.compile(r"^(Microsoft (?:Word|PowerPoint|Excel) - |PowerPoint Presentation)", re.I)
_PATHLIKE_TITLE = re.compile(r"[\\/]|\.(dvi|pdf|docx?|tex|pptx?|txt|ps)$", re.I)
_OBJECT_REF = re.compile(r"IndirectObject\(\d+, \d+, \d+\)")


def _available() -> tuple[bool, str]:
    try:
        metadata.version("pypdf")
    except metadata.PackageNotFoundError:
        return False, "pypdf is not installed (pip install contextmax[pdf])"
    return True, ""


class _Capture(logging.Handler):
    """Collects pypdf's warnings so they land in the document's notes, not on the console."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        if message.startswith("fontTools is required"):
            message = "fontTools not installed: some font encodings may be approximate"
        message = _OBJECT_REF.sub("IndirectObject(…)", message)
        message = re.sub(r"\{.*\}", "{…}", message, flags=re.S)
        self.messages.append(squash(message)[:120])


def sane_title(value: str | None) -> str:
    """A metadata or first-line title worth showing: not a file path, not a producer stamp."""
    text = squash(str(value or ""))
    text = _TITLE_PREFIX.sub("", text).strip()
    if not text or len(text) < 3 or len(text) > 200 or _PATHLIKE_TITLE.search(text):
        return ""
    if text.lower() in ("untitled", "title page", "table of contents", "contents", "cover"):
        return ""
    if re.fullmatch(r"(slide|page|document|presentation|sheet)\s*\d*", text, re.I):
        return ""
    if sum(ch.isalpha() for ch in text) < 3:
        return ""
    return text


_TRAILING_PAGE = re.compile(r"(\s\d{1,4}|\s\.\s*)$")
_LETTER_SPACED = re.compile(r"\b([B-HJ-Z]) (?=[a-z]{2,}\b)")
_CHAPTER_LINE = re.compile(r"^(Chapter|Appendix|Part)\s+([0-9]+|[A-Z]|[IVX]+)$", re.I)
_BARE_NUMBER = re.compile(r"^\d{1,2}$")


def unspace(text: str) -> str:
    """Re-join letter-spaced capitals pypdf leaves in titles ("T rajectory" -> "Trajectory")."""
    return _LETTER_SPACED.sub(r"\1", text)


def title_like(line: str, max_words: int = 10) -> bool:
    """A short capitalised line without terminal punctuation or a trailing page number."""
    stripped = line.strip()
    words = stripped.split()
    if not stripped or len(words) > max_words or not stripped[:1].isupper():
        return False
    if stripped.endswith((".", ",", ";", ":")) or _TRAILING_PAGE.search(stripped):
        return False
    letters = sum(ch.isalpha() for ch in stripped)
    return letters >= 0.6 * len(stripped.replace(" ", ""))


def classify_heading(line: str) -> tuple[bool, int, int | None]:
    """(is heading, depth, major section number or None) for one extracted text line."""
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False, 0, None
    numbered = NUMBERED_HEADING.match(stripped) is not None
    if stripped.endswith((".", ",", ";")) and not numbered:
        return False, 0, None
    words = stripped.split()
    if len(words) > 14:
        return False, 0, None
    if stripped.lower().rstrip(":") in KEYWORD_HEADINGS:
        return True, 1, None
    if numbered:
        number, rest = split_number(stripped)
        if number is None and re.match(r"^(Chapter|Appendix)\s", stripped, re.I):
            return True, 1, None
        if not number or re.fullmatch(r"\d{4}", number):  # a year, not a section number
            return False, 0, None
        if _TRAILING_PAGE.search(stripped) or ". . ." in stripped:  # a contents entry
            return False, 0, None
        if not title_like(rest, max_words=13):
            return False, 0, None
        major = int(number.split(".")[0]) if number[:1].isdigit() else None
        if number == "0":  # a bare zero starts matrix rows, never a section
            return False, 0, None
        return True, number.count(".") + 1, major
    letters = [ch for ch in stripped if ch.isalpha()]
    if (
        len(letters) >= 4
        and all(ch.isupper() for ch in letters)
        and 1 <= len(words) <= 8
        and not stripped[:1].isdigit()
        and not _TRAILING_PAGE.search(stripped)
    ):
        return True, 1, None
    return False, 0, None


def looks_like_heading(line: str) -> tuple[bool, int]:
    """(is heading, depth) for one extracted text line."""
    is_heading, depth, _ = classify_heading(line)
    return is_heading, depth


class PdfAdapter:
    id = "pdf-v1"
    determinism = "version-bound"

    @property
    def version(self) -> str:
        try:
            return metadata.version("pypdf")
        except metadata.PackageNotFoundError:
            return "missing"

    def available(self) -> tuple[bool, str]:
        return _available()

    def extract(self, key: str, data: bytes) -> DocumentTree:
        ok, reason = _available()
        if not ok:
            raise ExtractionError(reason)
        logger = logging.getLogger("pypdf")
        capture = _Capture()
        old_level = logger.level
        logger.addHandler(capture)
        logger.setLevel(logging.WARNING)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = self._extract(key, data)
        finally:
            logger.removeHandler(capture)
            logger.setLevel(old_level)
        unique = list(dict.fromkeys(capture.messages))
        if unique:
            more = f" (+{len(unique) - MAX_NOTES} more)" if len(unique) > MAX_NOTES else ""
            tree.notes.append("pypdf: " + "; ".join(unique[:MAX_NOTES]) + more)
        return tree

    def _extract(self, key: str, data: bytes) -> DocumentTree:
        from pypdf import PdfReader

        tree = DocumentTree(
            key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism
        )
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception as exc:
                    raise ExtractionError(f"password protected: {exc.__class__.__name__}") from exc
            n_pages = len(reader.pages)
        except ExtractionError:
            raise
        except Exception as exc:  # pypdf raises many types on damaged files
            raise ExtractionError(
                f"unreadable PDF: {exc.__class__.__name__}: {squash(str(exc))[:120]}"
            ) from exc
        if n_pages > MAX_PAGES:
            tree.notes.append(f"TRUNCATED: first {MAX_PAGES} of {n_pages} pages")
        tree.pages = n_pages
        meta_title = ""
        try:
            meta = reader.metadata
        except Exception:
            meta = None
        if meta is not None:
            for field in ("title", "author", "subject", "creator", "producer"):
                try:
                    value = getattr(meta, field, None)
                except Exception:
                    value = None
                if value:
                    tree.metadata[field] = squash(str(value))[:200]
            meta_title = sane_title(tree.metadata.get("title"))

        outline: list[tuple[int, int, str]] = []  # (page index, depth, title)
        try:
            self._walk_outline(reader, reader.outline, 1, outline)
        except Exception as exc:  # a broken outline never blocks the text
            tree.notes.append(f"outline unreadable: {exc.__class__.__name__}")
        outline.sort(key=lambda h: (h[0], h[1]))
        by_page: dict[int, list[tuple[int, str]]] = {}
        for page_index, depth, title in outline:
            by_page.setdefault(page_index, []).append((depth, title))
        derive = not outline
        tree.metadata["toc_source"] = "outline" if outline else "derived"

        total_chars = 0
        failed_pages = 0
        first_line = ""
        state = {"major": 0}
        for index in range(min(n_pages, MAX_PAGES)):
            page_no = index + 1
            tree.blocks.append(Block(kind="page", page=page_no, line=page_no, end_line=page_no))
            for depth, title in by_page.get(index, []):
                number, clean = split_number(title)
                tree.blocks.append(
                    Block(kind="heading", text=clean, level=depth, number=number, page=page_no,
                          line=page_no, end_line=page_no)
                )
            try:
                page = reader.pages[index]
                text = page.extract_text() or ""
            except Exception as exc:
                failed_pages += 1
                if failed_pages <= MAX_NOTES:
                    tree.notes.append(
                        f"page {page_no}: text extraction failed ({exc.__class__.__name__})"
                    )
                continue
            total_chars += len(text.strip())
            if index == 0:
                first_line = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")
            for para, heading_depth in self._paragraphs(text, derive, state):
                if heading_depth:
                    number, clean = split_number(para)
                    tree.blocks.append(
                        Block(kind="heading", text=unspace(clean), level=heading_depth, number=number,
                              page=page_no, line=page_no, end_line=page_no)
                    )
                else:
                    tree.blocks.append(
                        Block(kind="paragraph", text=para, page=page_no, line=page_no, end_line=page_no)
                    )
                    for url in _URL.findall(para):
                        tree.blocks.append(
                            Block(kind="link", text=url, target=url, page=page_no, line=page_no,
                                  end_line=page_no)
                        )
            for target, label in self._links(page):
                tree.blocks.append(
                    Block(kind="link", text=label, target=target, page=page_no, line=page_no,
                          end_line=page_no)
                )
        if failed_pages > MAX_NOTES:
            tree.notes.append(f"{failed_pages} pages failed text extraction in total")
        if n_pages and total_chars / n_pages < SCAN_CHARS_PER_PAGE:
            tree.metadata["scan_detected"] = True
            tree.notes.append(
                f"scan detected: {total_chars} characters over {n_pages} pages; "
                "content is NOT in the index (no OCR)"
            )

        scanned = bool(tree.metadata.get("scan_detected"))
        first_heading = next(
            (b for b in tree.blocks if b.kind == "heading" and sane_title(b.text)), None
        )
        if meta_title:
            tree.title, tree.metadata["title_source"] = meta_title, "metadata"
        elif not scanned and sane_title(first_line) and 2 <= len(first_line.split()) <= 20:
            tree.title, tree.metadata["title_source"] = unspace(sane_title(first_line)), "first-line"
        elif not scanned and first_heading:
            tree.title, tree.metadata["title_source"] = sane_title(first_heading.text), "heading"
        else:
            tree.title, tree.metadata["title_source"] = key.rsplit("/", 1)[-1], "filename"
        no_headings = not any(b.kind == "heading" for b in tree.blocks)
        if derive and no_headings and not tree.metadata.get("scan_detected"):
            tree.notes.append(
                "no bookmarks and no headings could be derived; the document is one section"
            )
        return tree

    def _walk_outline(
        self, reader: Any, items: Any, depth: int, out: list[tuple[int, int, str]]
    ) -> None:
        for item in items:
            if isinstance(item, list):
                self._walk_outline(reader, item, depth + 1, out)
                continue
            title = squash(str(getattr(item, "title", "") or ""))
            if not title:
                continue
            try:
                page_index = reader.get_destination_page_number(item)
            except Exception:
                page_index = 0
            out.append((max(page_index or 0, 0), depth, title))

    @staticmethod
    def _paragraphs(text: str, derive: bool, state: dict[str, int]) -> list[tuple[str, int]]:
        """Paragraphs from pypdf's one-line-per-text-line output: blank lines, headings and
        short sentence-ending lines break paragraphs; hyphenated line breaks are re-joined.
        `state["major"]` carries the last accepted chapter number across pages so that
        out-of-sequence numbers (lists of figures, stray "5.12" lines) are not headings."""
        lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
        max_len = max((len(ln) for ln in lines), default=0)
        out: list[tuple[str, int]] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                joined = squash(" ".join(buffer))
                if joined:
                    out.append((joined, 0))
                buffer.clear()

        skip_next = False
        for pos, line in enumerate(lines):
            if skip_next:
                skip_next = False
                continue
            if not line:
                flush()
                continue
            if derive:
                nxt = next((ln for ln in lines[pos + 1 : pos + 3] if ln), "")
                chapter = _CHAPTER_LINE.match(line)
                if (chapter or _BARE_NUMBER.match(line)) and nxt and title_like(nxt, max_words=8):
                    label = chapter.group(2) if chapter else line
                    if label.isdigit():
                        state["major"] = int(label)
                    flush()
                    out.append((f"{label} {squash(nxt)}", 1))
                    skip_next = True
                    continue
                is_heading, depth, major = classify_heading(line)
                if is_heading and major is not None:
                    if major > state["major"] + 1:
                        is_heading = False  # out of sequence: a list entry or a stray number
                    else:
                        state["major"] = max(state["major"], major)
                if is_heading:
                    flush()
                    out.append((squash(line), depth))
                    continue
            if buffer and buffer[-1].endswith("-") and line[:1].islower():
                buffer[-1] = buffer[-1][:-1] + line
            else:
                buffer.append(line)
            if line.endswith((".", "?", "!", ":")) and len(line) < 0.7 * max_len:
                flush()
        flush()
        return out

    @staticmethod
    def _links(page: Any) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        try:
            annots = page.get("/Annots") or []
        except Exception:
            return found
        for annot in annots:
            try:
                obj: Any = annot.get_object()
                if obj.get("/Subtype") != "/Link":
                    continue
                action = obj.get("/A")
                if action is not None and action.get("/URI"):
                    uri = str(action.get("/URI"))
                    found.append((uri, uri))
            except Exception:
                continue
        return found
