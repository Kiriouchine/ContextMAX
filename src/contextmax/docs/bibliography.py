# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Bibliographies parsed from extracted text, and the in-text citations that point at them.

A references section (heading matching REFERENCE_HEADINGS) is split into entries by `[n]`
markers, `n.` numbering or blank lines; each entry yields authors, year, title (quoted text or
the segment after the authors), DOI and URL. Entries resolve to a project document by DOI or
title (or, low confidence, by a file stem that contains the title), and to a BibTeX entry by
DOI or title. In-text `[12]`, `[3, 5-7]` and `(Smith et al., 2020)` citations resolve to the
entries. Everything unresolved stays visible with its raw text."""

from __future__ import annotations

import re
from typing import Any

from contextmax.docs.base import DocumentTree
from contextmax.docs.structure import Structure
from contextmax.model.ids import doc_id, ref_id

REFERENCE_HEADINGS = re.compile(
    r"^(references|bibliography|works cited|literature(?: cited)?|literatuur|referenties|sources|citations|reference list)\b",
    re.I,
)
NUMBERED = re.compile(r"\[(\d{1,3})\]\s*")
DOTTED = re.compile(r"(?:^|\n)\s*(\d{1,3})\.\s+")
YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
DOI = re.compile(r"\b(10\.\d{4,9}/[^\s,;\"”)]+)")
URL = re.compile(r"https?://[^\s<>\"”)]+")
QUOTED_TITLE = re.compile(r"[“\"”]\s*([^“”\"]{6,240}?)\s*[”\"]")
IN_TEXT = re.compile(r"\[(\d{1,3}(?:\s*[,–—-]\s*\d{1,3})*)\]")  # noqa: RUF001 - ranges use en and em dashes
AUTHOR_YEAR = re.compile(r"\(([A-Z][A-Za-z'\-]+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z'\-]+)?,?\s+(1[89]\d{2}|20\d{2})[a-z]?\)")
MAX_ENTRIES = 2000
MAX_CITATIONS = 5000


def norm_title(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def norm_stem(key: str) -> str:
    stem = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return " ".join(re.findall(r"[a-z0-9]+", stem.lower()))


def split_entries(body: str) -> list[tuple[str | None, str]]:
    """(number or None, entry text) in document order."""
    markers = list(NUMBERED.finditer(body))
    if len(markers) >= 2:
        out = []
        for i, m in enumerate(markers):
            end = markers[i + 1].start() if i + 1 < len(markers) else len(body)
            text = body[m.end() : end].strip()
            if text:
                out.append((m.group(1), text))
        return out[:MAX_ENTRIES]
    dotted = list(DOTTED.finditer(body))
    if len(dotted) >= 2:
        out = []
        for i, m in enumerate(dotted):
            end = dotted[i + 1].start() if i + 1 < len(dotted) else len(body)
            text = body[m.end() : end].strip()
            if text:
                out.append((m.group(1), text))
        return out[:MAX_ENTRIES]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    out = [(None, p) for p in paragraphs if len(p) >= 20 and YEAR.search(p)]
    return out[:MAX_ENTRIES]


def parse_entry(text: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"raw": " ".join(text.split())[:400]}
    doi = DOI.search(text)
    entry["doi"] = doi.group(1).rstrip(".") if doi else ""
    url = URL.search(text)
    entry["url"] = url.group(0).rstrip(".,") if url else ""
    years = YEAR.findall(text)
    entry["year"] = years[-1] if years else ""
    quoted = QUOTED_TITLE.search(text)
    if quoted and len(quoted.group(1).split()) >= 2:
        entry["title"] = " ".join(quoted.group(1).split()).strip(" .,")
        entry["authors"] = " ".join(text[: quoted.start()].split()).strip(" .,;:")
    else:
        # Unquoted entry: author segments end with an initial ("A.", "R. E."), the title is the
        # next segment that is not just a year.
        segments = [s.strip() for s in re.split(r"(?<=\.)\s+", " ".join(text.split())) if s.strip()]
        author_parts: list[str] = []
        rest = list(segments)
        while rest and re.search(r"\b[A-Z]\.$", rest[0]):
            author_parts.append(rest.pop(0))
        while rest and re.fullmatch(r"\(?(?:1[89]|20)\d{2}[a-z]?\)?[.,]?", rest[0]):
            rest.pop(0)
        entry["authors"] = " ".join(author_parts).strip(" .,;:")
        if rest:
            entry["title"] = rest[0].strip(" .,;:")[:240]
        else:
            entry["title"] = " ".join(text.split())[:160].strip(" .,;:")
    entry["authors"] = entry["authors"][:200]
    return entry


def surnames(authors: str) -> set[str]:
    return {w.strip(".,") for w in re.findall(r"[A-Z][A-Za-z'\-]{2,}", authors)}


def _row(
    key: str,
    ref_key: str,
    ref_kind: str,
    raw: str,
    name: str,
    section: str | None,
    line: int,
    page: int | None,
    page_unit: str,
    line_unit: str,
    resolved: str | None,
    candidates: list[str],
    external: bool,
    confidence: str | None,
    evidence: str,
    **extra: Any,
) -> dict[str, Any]:
    if page:
        where = f"p.{page}" if page_unit == "page" else f"{page_unit} {page}"
        cite = f"{key} {where}"
    elif line_unit == "paragraph":
        cite = f"{key} ¶{line}" if line else key
    else:
        cite = f"{key}:{line}" if line else key
    return {
        "id": ref_id(key, ref_key),
        "kind": "reference",
        "family": "doc",
        "ref_kind": ref_kind,
        "name": name or raw,
        "raw": raw,
        "doc": doc_id(key),
        "section": section,
        "file": key,
        "line": line,
        "resolved": resolved,
        "candidates": sorted(candidates),
        "external": external,
        "confidence": confidence,
        "evidence": evidence,
        "page": page,
        "cite": cite,
        **extra,
    }


def parse_bibliography(
    tree: DocumentTree,
    key: str,
    structure: Structure,
    doc_titles: dict[str, list[str]],
    doc_stems: dict[str, str],
    bib_dois: dict[str, str],
    bib_titles: dict[str, str],
) -> list[dict[str, Any]]:
    """Reference rows: parsed entries (`ref:<key>#b<n>`) and in-text citations (`ref:<key>#c<n>`)."""
    page_unit = tree.metadata.get("page_unit", "page")
    line_unit = tree.metadata.get("line_unit", "line")
    own = doc_id(key)
    bib_sections = [s for s in structure.sections if REFERENCE_HEADINGS.match(s.title.strip().rstrip(":."))]
    rows: list[dict[str, Any]] = []
    entries_by_number: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}
    for section in bib_sections:
        body = structure.text[section.text_start : section.text_end]
        body = body.split("\n", 1)[1] if body.startswith("#") and "\n" in body else body
        for number, text in split_entries(body):
            entry = parse_entry(text)
            base = f"b{number}" if number else f"b{len(entries) + 1}"
            count = seen_ids.get(base, 0) + 1
            seen_ids[base] = count
            ref_key = base if count == 1 else f"{base}~{count}"
            resolved, candidates, confidence, evidence, external = None, [], None, "parsed", True
            title_key = norm_title(entry["title"])
            if entry["doi"] and entry["doi"].lower() in bib_dois:
                resolved, confidence, evidence, external = bib_dois[entry["doi"].lower()], "high", "doi-bibtex", False
            elif title_key and title_key in bib_titles:
                resolved, confidence, evidence, external = bib_titles[title_key], "medium", "title-bibtex", False
            elif title_key and title_key in doc_titles:
                owners = [doc_id(k) for k in doc_titles[title_key] if k != key]
                if len(owners) == 1:
                    resolved, confidence, evidence, external = owners[0], "medium", "title", False
                elif owners:
                    candidates, evidence = owners, "title-ambiguous"
            if resolved is None and not candidates and title_key and len(title_key.split()) >= 3:
                stem_hits = [doc_id(k) for k, stem in doc_stems.items() if k != key and title_key in stem]
                if len(stem_hits) == 1:
                    resolved, confidence, evidence, external = stem_hits[0], "low", "stem", False
            line = section.line
            page = section.page
            row = _row(
                key, ref_key, "bibentry", entry["raw"], entry["title"] or entry["raw"][:80], section.id, line, page,
                page_unit, line_unit, resolved, candidates, external, confidence, evidence,
                entry_key=number or ref_key, entry_type="parsed", title=entry["title"], authors=entry["authors"],
                year=entry["year"], doi=entry["doi"], url=entry["url"], journal="",
            )
            rows.append(row)
            entries.append(row)
            if number and number not in entries_by_number:
                entries_by_number[number] = row["id"]
    if not entries:
        return rows

    # In-text citations outside the bibliography sections.
    bib_ranges = [(s.text_start, s.text_end) for s in bib_sections]
    n_cit = 0
    section_of = structure.block_section
    for idx, block in enumerate(tree.blocks):
        if block.kind not in ("paragraph", "list_item", "table") or not block.text:
            continue
        offset = structure.block_offsets[idx] if idx < len(structure.block_offsets) else 0
        if any(start <= offset < end for start, end in bib_ranges):
            continue
        section = section_of[idx] if idx < len(section_of) else None
        for m in IN_TEXT.finditer(block.text):
            numbers: list[str] = []
            for part in re.split(r"\s*,\s*", m.group(1)):
                rng = re.split(r"\s*[–—-]\s*", part)  # noqa: RUF001 - ranges use en and em dashes
                if len(rng) == 2 and rng[0].isdigit() and rng[1].isdigit() and int(rng[1]) >= int(rng[0]):
                    numbers.extend(str(n) for n in range(int(rng[0]), min(int(rng[1]), int(rng[0]) + 20) + 1))
                elif part.strip().isdigit():
                    numbers.append(part.strip())
            for number in numbers:
                if n_cit >= MAX_CITATIONS:
                    break
                n_cit += 1
                target = entries_by_number.get(number)
                rows.append(
                    _row(
                        key, f"c{n_cit}", "citation", f"[{number}]", f"[{number}]", section, block.line, block.page,
                        page_unit, line_unit, target, [], target is None, "high" if target else None,
                        "numbered" if target else "numbered-unresolved",
                    )
                )
        for m in AUTHOR_YEAR.finditer(block.text):
            if n_cit >= MAX_CITATIONS:
                break
            surname, year = m.group(1), m.group(2)
            matches = [e for e in entries if e["year"] == year and surname in surnames(e["authors"])]
            n_cit += 1
            target = matches[0]["id"] if len(matches) == 1 else None
            rows.append(
                _row(
                    key, f"c{n_cit}", "citation", m.group(0), f"{surname} {year}", section, block.line, block.page,
                    page_unit, line_unit, target, [e["id"] for e in matches] if len(matches) > 1 else [],
                    not matches, "medium" if target else None,
                    "author-year" if target else ("author-year-ambiguous" if matches else "author-year-unresolved"),
                )
            )
    _ = own
    return rows
