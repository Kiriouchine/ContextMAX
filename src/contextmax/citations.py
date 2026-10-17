"""One way to cite, everywhere: the Ask page, the values page, the documents page, the Atlas and the skill.

  a value      Document · stage · page 12, line 340 · §3.1 PID step       (a PDF)
               Document · stage · line 88 · §Tuning                       (Word, Markdown, text)
               Workbook · stage · Sheet!B7                                (a workbook's cell)
  a passage    Document · stage · page 12, lines 340–349
  code         code base · control/pid.c:40–52

Lines count in the document's extracted text, which "Show the line" opens at that line; pages are the PDF's.
"""
from __future__ import annotations

import bisect


def page_of(page_lines: list[int] | None, line: int | None) -> int | None:
    """The page a line of a PDF's text is on, from where each page starts."""
    if not page_lines or not line:
        return None
    return bisect.bisect_right(page_lines, line) or None


def value(row: dict, title: str) -> str:
    """Where one value is stated (a value row of params.jsonl, or a document of value-to-code.jsonl)."""
    parts = [title]
    if row.get("stage"):
        parts.append(row["stage"])
    if row.get("sheet") and row.get("cell"):
        parts.append(f"{row['sheet']}!{row['cell']}")
    elif row.get("line_no"):
        parts.append((f"page {row['page']}, " if row.get("page") else "") + f"line {row['line_no']}")
    if row.get("section") and not (row.get("sheet") and row.get("cell")):
        parts.append(f"§{row['section']}")
    return " · ".join(parts)


def passage(title: str, stage: str | None, first: int, last: int, page_lines: list[int] | None = None) -> str:
    """Where some lines of a document are."""
    page = page_of(page_lines, first)
    end = page_of(page_lines, last)
    pages = f"page {page}" if page and page == end else f"pages {page}–{end}" if page and end else ""
    lines = f"line {first}" if first == last else f"lines {first}–{last}"
    return " · ".join(p for p in (title, stage or "", ", ".join(x for x in (pages, lines) if x)) if p)


def code(label: str, file: str, first: int, last: int | None = None) -> str:
    return f"{label} · {file}:{first}" + (f"–{last}" if last and last != first else "")
