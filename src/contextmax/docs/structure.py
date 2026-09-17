# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""From an adapter's block list to an outline, section ids, a text cache and offsets.

Section ids follow ADR-0003: `doc:<path>#<number>` when the document numbers its headings,
else `doc:<path>#<slug-chain>`, with `~n` for duplicates. Section text ranges are character
offsets into the rendered text cache so a query can return exactly the section's words.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contextmax.docs.base import Block, DocumentTree
from contextmax.model.ids import section_id, slug

PREVIEW_CHARS = 160


@dataclass
class Section:
    id: str
    title: str
    depth: int
    number: str | None
    parent: str | None
    order: int
    line: int
    end_line: int
    text_start: int
    text_end: int
    n_words: int = 0
    preview: str = ""
    path: str = ""
    n_blocks: int = 0
    page: int | None = None
    end_page: int | None = None


@dataclass
class Structure:
    text: str
    sections: list[Section] = field(default_factory=list)
    toc: list[str] = field(default_factory=list)
    block_offsets: list[int] = field(default_factory=list)  # char offset of each block in `text`
    block_section: list[str | None] = field(default_factory=list)  # section id owning each block
    n_words: int = 0
    tables: int = 0
    figures: int = 0
    footnotes: int = 0
    code_blocks: int = 0


def render_block(block: Block, depth: int | None = None) -> str:
    kind = block.kind
    if kind == "heading":
        level = depth or max(block.level, 1)
        number = f"{block.number} " if block.number else ""
        return f"{'#' * min(level, 6)} {number}{block.text}"
    if kind == "title":
        return f"# {block.text}" if block.text else ""
    if kind == "paragraph":
        return block.text
    if kind == "list_item":
        return "  " * (max(block.level, 1) - 1) + "- " + block.text
    if kind == "table":
        body = block.text or ("\n".join("\t".join(r) for r in block.rows or []))
        return body
    if kind == "code":
        return f"```{block.lang or ''}\n{block.text}\n```"
    if kind == "figure":
        label = block.text or ""
        target = f" ({block.target})" if block.target else ""
        return f"[figure: {label}]{target}" if (label or target) else ""
    if kind == "footnote":
        return f"[^{block.target}]: {block.text}"
    if kind == "math":
        return f"[equation] {block.text}" if block.text else "[equation]"
    if kind == "include":
        return f"[include: {block.target}]"
    if kind == "cell":
        return block.text
    if kind == "page":
        return f"[page {block.page}]"
    return ""  # link, citation, label, ref: inline artifacts, not text


def build(tree: DocumentTree, key: str) -> Structure:
    blocks = tree.blocks
    used_levels = sorted({b.level for b in blocks if b.kind == "heading" and b.level > 0})
    depth_of = {level: idx + 1 for idx, level in enumerate(used_levels)}
    all_numbered = bool(used_levels) and all(b.number for b in blocks if b.kind == "heading")

    parts: list[str] = []
    offsets: list[int] = []
    cursor = 0
    if tree.title and not any(
        b.kind in ("heading", "title") and b.text == tree.title for b in blocks
    ):
        parts.append(f"# {tree.title}")
        cursor += len(parts[-1]) + 2
    for block in blocks:
        rendered = render_block(
            block, depth_of.get(block.level) if block.kind == "heading" else None
        )
        offsets.append(cursor)
        if rendered:
            parts.append(rendered)
            cursor += len(rendered) + 2
    text = "\n\n".join(parts) + ("\n" if parts else "")

    structure = Structure(text=text, block_offsets=offsets)
    structure.n_words = len(text.split())
    structure.tables = sum(1 for b in blocks if b.kind == "table")
    structure.figures = sum(1 for b in blocks if b.kind == "figure")
    structure.footnotes = sum(1 for b in blocks if b.kind == "footnote")
    structure.code_blocks = sum(1 for b in blocks if b.kind == "code")

    # Sections from headings.
    sections: list[Section] = []
    stack: list[Section] = []
    seen_ids: dict[str, int] = {}
    heading_indices = [i for i, b in enumerate(blocks) if b.kind == "heading"]
    for order, idx in enumerate(heading_indices, start=1):
        block = blocks[idx]
        depth = depth_of.get(block.level, 1)
        while stack and stack[-1].depth >= depth:
            stack.pop()
        parent = stack[-1] if stack else None
        if all_numbered and block.number:
            path = block.number
        else:
            own = slug(f"{block.number} {block.text}" if block.number else block.text)
            path = f"{parent.path}/{own}" if parent else own
        base = path
        count = seen_ids.get(base, 0) + 1
        seen_ids[base] = count
        if count > 1:
            path = f"{base}~{count}"
        section = Section(
            id=section_id(key, path),
            title=block.text,
            depth=depth,
            number=block.number,
            parent=parent.id if parent else None,
            order=order,
            line=block.line,
            end_line=block.end_line,
            text_start=offsets[idx],
            text_end=len(text),
            path=path,
            page=block.page,
            end_page=block.page,
        )
        sections.append(section)
        stack.append(section)
    # Close ranges: a section ends where the next heading of the same or higher depth starts.
    for i, section in enumerate(sections):
        for later in sections[i + 1 :]:
            if later.depth <= section.depth:
                section.text_end = later.text_start
                section.end_line = max(section.line, later.line - 1)
                if later.page is not None and section.page is not None:
                    section.end_page = max(section.page, later.page)
                break
        else:
            last_line = max((b.end_line for b in blocks), default=section.line)
            section.end_line = max(section.line, last_line)
            if section.page is not None:
                section.end_page = max((b.page for b in blocks if b.page), default=section.page)
        body = text[section.text_start : section.text_end]
        section.n_words = len(body.split())
        first_line_end = body.find("\n")
        preview_src = body[first_line_end + 1 :] if first_line_end >= 0 else ""
        section.preview = " ".join(preview_src.split())[:PREVIEW_CHARS]
    # Which section owns each block (innermost by text offset).
    structure.block_section = []
    for idx, _block in enumerate(blocks):
        owner: str | None = None
        for section in sections:
            if section.text_start <= offsets[idx] < section.text_end:
                owner = section.id  # later sections are deeper or later; keep the innermost
        structure.block_section.append(owner)
    for section in sections:
        section.n_blocks = sum(1 for owner in structure.block_section if owner == section.id)
    structure.sections = sections
    structure.toc = [s.id for s in sections]
    return structure
