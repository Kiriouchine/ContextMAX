# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Parameters: named quantities. A parameter's identity is its label, never its number.

Spreadsheet cells arrive as `cell` blocks whose `extra["param"]` the sheet adapter filled in;
prose quantities (`2.0 deg`, `50 Hz`) are found here in paragraphs, list items and table rows,
with the nearest preceding phrase as the label. Every record carries where it came from."""

from __future__ import annotations

import re
from typing import Any

from contextmax.docs.base import DocumentTree
from contextmax.docs.structure import Structure
from contextmax.docs.units import alias_table, normalise_unit, quantity_pattern
from contextmax.model.ids import doc_id

MAX_PROSE_PER_DOC = 200
LABEL_WORDS = 6
STOP_EDGE = {
    "of", "to", "at", "is", "was", "are", "be", "by", "in", "on", "for", "the", "a", "an", "within", "than",
    "about", "approximately", "around", "=", "≈", "~", "from", "and", "or", "with", "as", "that", "this",
    "which", "it", "its", "has", "have", "had", "set", "equal", "equals", "value", "values", "roughly", "up",
    "down", "below", "above", "under", "over", "between", "per", "every", "each", "least", "most", "only",
}
SENTENCE_SPLIT = re.compile(r"(?<=[a-zA-Z\)])[.;!?]\s+|\n")  # a colon introduces a value, so it stays
TOKEN = re.compile(r"[A-Za-z0-9_µ°%/^·.-]+")


def norm_label(label: str) -> str:
    """Comparison key: lower-case words separated by single spaces."""
    words = re.findall(r"[a-z0-9µ°%/^]+", label.lower().replace("_", " "))
    return " ".join(words)


def _label_before(text: str, end: int, floor: int = 0) -> str:
    """The phrase preceding position `end` inside its sentence (and after `floor`, the end of
    the previous quantity), trimmed of edge stop words."""
    head = text[floor:end]
    sentence = SENTENCE_SPLIT.split(head)[-1]
    words = TOKEN.findall(sentence)
    words = words[-LABEL_WORDS:]
    while words and (words[-1].lower() in STOP_EDGE or not re.search(r"[A-Za-z]", words[-1])):
        words.pop()
    while words and (words[0].lower() in STOP_EDGE or not re.search(r"[A-Za-z]", words[0])):
        words.pop(0)  # table debris such as "4 0 029" never starts a label
    label = " ".join(words)
    return label if re.search(r"[A-Za-z]{3,}", label) else ""


def _number(text: str) -> float | int | None:
    cleaned = text.replace(",", ".") if text.count(",") == 1 and "." not in text else text.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value.is_integer() and "." not in cleaned and "e" not in cleaned.lower():
        return int(value)
    return value


def prose_quantities(
    tree: DocumentTree, key: str, structure: Structure, units_extra: list[str] | None = None
) -> list[dict[str, Any]]:
    pattern = quantity_pattern(units_extra)
    table = alias_table(units_extra)
    rows: list[dict[str, Any]] = []
    own = doc_id(key)
    counters: dict[str | None, int] = {}
    page_unit = tree.metadata.get("page_unit", "page")
    line_prefix = " ¶" if tree.metadata.get("line_unit") == "paragraph" else ":"
    for idx, block in enumerate(tree.blocks):
        if block.kind not in ("paragraph", "list_item", "table"):
            continue
        text = block.text or ("\n".join("\t".join(r) for r in block.rows or []))
        if not text:
            continue
        section = structure.block_section[idx] if idx < len(structure.block_section) else None
        last_end = 0
        for m in pattern.finditer(text):
            value = _number(m.group("num"))
            if value is None:
                continue
            raw_unit = m.group("long") or m.group("short")
            label = _label_before(text, m.start(), last_end)
            last_end = m.end()
            if not label or len(label) < 2:
                continue
            n = counters.get(section, 0) + 1
            counters[section] = n
            if n > MAX_PROSE_PER_DOC:
                continue
            sec_path = section.split("#", 1)[1] if section and "#" in section else "_"
            if block.page:
                where = f"p.{block.page}" if page_unit == "page" else f"{page_unit} {block.page}"
                cite = f"{key} {where}"
            else:
                cite = f"{key}{line_prefix}{block.line}"
            rows.append(
                {
                    "id": f"param:{key}#{sec_path}~{n}",
                    "kind": "parameter",
                    "family": "doc",
                    "name": label,
                    "label": label,
                    "label_norm": norm_label(label),
                    "value": value,
                    "display": m.group("num"),
                    "unit": raw_unit,
                    "unit_norm": normalise_unit(raw_unit, table),
                    "formula": None,
                    "source_kind": "prose",
                    "doc": own,
                    "section": section,
                    "file": key,
                    "sheet": None,
                    "cell": None,
                    "header": None,
                    "hidden": False,
                    "line": block.line,
                    "page": block.page,
                    "context": text[max(0, m.start() - 60) : m.end() + 40].replace("\n", " ").strip(),
                    "cite": cite,
                }
            )
    total = sum(counters.values())
    if total > MAX_PROSE_PER_DOC:
        tree.notes.append(f"TRUNCATED: {total} prose quantities found, first {MAX_PROSE_PER_DOC} per section kept")
    return rows


def cell_parameters(tree: DocumentTree, key: str, structure: Structure) -> list[dict[str, Any]]:
    """Parameter rows from the sheet adapter's `cell` blocks."""
    rows: list[dict[str, Any]] = []
    own = doc_id(key)
    for idx, block in enumerate(tree.blocks):
        record = block.extra.get("param") if block.kind == "cell" else None
        if not record:
            continue
        section = structure.block_section[idx] if idx < len(structure.block_section) else None
        base = f"param:{key}#{record['sheet']}!{record['cell']}"
        common = {
            "kind": "parameter",
            "family": "doc",
            "doc": own,
            "section": section,
            "file": key,
            "line": block.line,
            "page": block.page,
            "cite": f"{key} {record['sheet']}!{record['cell']}",
        }
        rows.append({**common, "id": base, "name": record["label"], **record})
        for n, literal in enumerate(record.get("literals") or [], start=1):
            rows.append(
                {
                    **common,
                    **record,
                    "id": f"{base}~lit{n}",
                    "name": f"{record['label']} (literal in formula)",
                    "label": f"{record['label']} (literal in formula)",
                    "label_norm": norm_label(record["label"]) + " literal",
                    "value": literal,
                    "display": str(literal),
                    "unit": None,
                    "unit_norm": None,
                    "source_kind": "formula-literal",
                    "literals": None,
                }
            )
    for row in rows:
        row.pop("literals", None)
    return rows
