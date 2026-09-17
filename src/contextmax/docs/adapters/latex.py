# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`latex-v1`: sectioning, labels, references, citations, includes, figures, tables, code
listings, math and paragraphs from LaTeX source, by pattern. Comments are removed before
anything else so a commented-out \\cite never becomes an edge."""

from __future__ import annotations

import re

from contextmax.docs.adapters.common import decode, split_number, squash
from contextmax.docs.base import Block, DocumentTree

SECTION_LEVEL = {
    "part": 1,
    "chapter": 2,
    "section": 3,
    "subsection": 4,
    "subsubsection": 5,
    "paragraph": 6,
    "subparagraph": 7,
}
SECTION = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*(?:\[[^\]]*\])?\s*\{"
)
TITLE = re.compile(r"\\title\s*\{")
LABEL = re.compile(r"\\label\s*\{([^}]*)\}")
REF = re.compile(r"\\(ref|eqref|autoref|cref|Cref|pageref|nameref|vref)\s*\{([^}]*)\}")
CITE = re.compile(r"\\(cite[a-zA-Z*]*|nocite)\s*(?:\[[^\]]*\]\s*)*\{([^}]*)\}")
INCLUDE = re.compile(
    r"\\(input|include|subfile|bibliography|addbibresource|includegraphics|lstinputlisting)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}"
)
BEGIN = re.compile(r"\\begin\s*\{([a-zA-Z*]+)\}")
ACRONYM = re.compile(r"\\newacronym\s*(?:\[[^\]]*\]\s*)?\{([^}]*)\}\s*\{([^}]*)\}\s*\{([^}]*)\}")
GLOSSARY_ENTRY = re.compile(r"\\newglossaryentry\s*\{([^}]*)\}\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
CAPTION = re.compile(r"\\caption\s*(?:\[[^\]]*\])?\s*\{")
ITEM = re.compile(r"\\item\b\s*(?:\[[^\]]*\])?")
DISPLAY_MATH = re.compile(r"\\\[.*?\\\]|\$\$.*?\$\$", re.DOTALL)
INLINE_MATH = re.compile(r"(?<!\\)\$[^$\n]+?\$")
FORMAT_MACROS = re.compile(
    r"\\(?:textbf|textit|emph|texttt|underline|textsc|textsf|textrm|mbox|hbox|url|href|MakeUppercase|MakeLowercase)\s*\{"
)
COMMAND = re.compile(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?")
FLOAT_ENVS = {"figure", "figure*", "table", "table*", "wrapfigure", "subfigure"}
CODE_ENVS = {"verbatim", "lstlisting", "minted", "Verbatim", "alltt"}
MATH_ENVS = {
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "eqnarray",
    "displaymath",
    "math",
}
LIST_ENVS = {"itemize", "enumerate", "description"}


def _balanced(text: str, start: int) -> tuple[str, int]:
    """Return the content of the brace group starting at `start` (index of '{') and the index after it."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    return text[start + 1 :], n


def strip_comments(text: str) -> str:
    out: list[str] = []
    for line in text.split("\n"):
        i = 0
        cut = len(line)
        while i < len(line):
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "%":
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def clean_text(fragment: str) -> str:
    """Prose without markup: formatting macros unwrapped, other commands dropped, math kept short."""
    s = DISPLAY_MATH.sub(" [equation] ", fragment)
    s = INLINE_MATH.sub(lambda m: m.group(0), s)
    while True:
        m = FORMAT_MACROS.search(s)
        if not m:
            break
        inner, end = _balanced(s, m.end() - 1)
        s = s[: m.start()] + inner + s[end:]
    s = CITE.sub(lambda m: "[" + m.group(2) + "]", s)
    s = REF.sub(lambda m: "[" + m.group(2) + "]", s)
    s = LABEL.sub("", s)
    s = COMMAND.sub(" ", s)
    s = s.replace("~", " ").replace("{", "").replace("}", "")
    for escaped, plain in (("\\_", "_"), ("\\&", "&"), ("\\%", "%"), ("\\#", "#"), ("\\$", "$")):
        s = s.replace(escaped, plain)
    return squash(s)


class LatexAdapter:
    id = "latex-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        raw = decode(data)
        text = strip_comments(raw)
        tree = DocumentTree(
            key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism
        )
        offsets = [0]
        for idx, ch in enumerate(text):
            if ch == "\n":
                offsets.append(idx + 1)

        def line_of(pos: int) -> int:
            lo, hi = 0, len(offsets) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if offsets[mid] <= pos:
                    lo = mid
                else:
                    hi = mid - 1
            return lo + 1

        m = TITLE.search(text)
        if m:
            inner, _ = _balanced(text, m.end() - 1)
            tree.title = clean_text(inner) or None
            tree.blocks.append(
                Block(
                    kind="title",
                    text=tree.title or "",
                    line=line_of(m.start()),
                    end_line=line_of(m.start()),
                )
            )

        # Walk the document once, emitting blocks in order and collecting prose between them.
        events: list[tuple[int, int, Block]] = []  # (start, end, block)
        for m in SECTION.finditer(text):
            inner, end = _balanced(text, m.end() - 1)
            number, clean = split_number(clean_text(inner))
            events.append(
                (
                    m.start(),
                    end,
                    Block(
                        kind="heading",
                        text=clean,
                        line=line_of(m.start()),
                        end_line=line_of(end),
                        level=SECTION_LEVEL[m.group(1)],
                        number=number,
                    ),
                )
            )
        for m in LABEL.finditer(text):
            events.append(
                (
                    m.start(),
                    m.end(),
                    Block(
                        kind="label",
                        text=m.group(1).strip(),
                        line=line_of(m.start()),
                        end_line=line_of(m.start()),
                        target=m.group(1).strip(),
                    ),
                )
            )
        for m in REF.finditer(text):
            for target in [t.strip() for t in m.group(2).split(",") if t.strip()]:
                events.append(
                    (
                        m.start(),
                        m.end(),
                        Block(
                            kind="ref",
                            text=target,
                            line=line_of(m.start()),
                            end_line=line_of(m.start()),
                            target=target,
                            extra={"ref_kind": m.group(1)},
                        ),
                    )
                )
        for m in CITE.finditer(text):
            for keyname in [k.strip() for k in m.group(2).split(",") if k.strip()]:
                events.append(
                    (
                        m.start(),
                        m.end(),
                        Block(
                            kind="citation",
                            text=keyname,
                            line=line_of(m.start()),
                            end_line=line_of(m.start()),
                            target=keyname,
                            extra={"command": m.group(1)},
                        ),
                    )
                )
        for m in ACRONYM.finditer(text):
            events.append(
                (
                    m.start(),
                    m.end(),
                    Block(
                        kind="term",
                        text=clean_text(m.group(3)).strip(),
                        target=m.group(2).strip(),
                        line=line_of(m.start()),
                        end_line=line_of(m.start()),
                        extra={"definition": clean_text(m.group(3)).strip(), "key": m.group(1).strip(), "command": "newacronym"},
                    ),
                )
            )
        for m in GLOSSARY_ENTRY.finditer(text):
            body = m.group(2)
            name = re.search(r"name\s*=\s*\{([^}]*)\}", body)
            desc = re.search(r"description\s*=\s*\{([^}]*)\}", body)
            if name:
                events.append(
                    (
                        m.start(),
                        m.end(),
                        Block(
                            kind="term",
                            text=clean_text(name.group(1)).strip(),
                            target=None,
                            line=line_of(m.start()),
                            end_line=line_of(m.start()),
                            extra={"definition": clean_text(desc.group(1)).strip() if desc else None, "key": m.group(1).strip(), "command": "newglossaryentry"},
                        ),
                    )
                )
        for m in INCLUDE.finditer(text):
            target = m.group(2).strip()
            kind = "figure" if m.group(1) == "includegraphics" else "include"
            events.append(
                (
                    m.start(),
                    m.end(),
                    Block(
                        kind=kind,
                        text=target if kind == "include" else "",
                        line=line_of(m.start()),
                        end_line=line_of(m.start()),
                        target=target,
                        extra={"command": m.group(1)},
                    ),
                )
            )
        # Environments: floats with captions, code, math, lists.
        for m in BEGIN.finditer(text):
            env = m.group(1)
            end_match = re.compile(r"\\end\s*\{" + re.escape(env) + r"\}").search(text, m.end())
            end = end_match.end() if end_match else len(text)
            body = text[m.end() : (end_match.start() if end_match else len(text))]
            if env in FLOAT_ENVS:
                cap = CAPTION.search(body)
                caption = clean_text(_balanced(body, cap.end() - 1)[0]) if cap else ""
                kind = "table" if env.startswith("table") else "figure"
                graphic = INCLUDE.search(body)
                target = (
                    graphic.group(2).strip()
                    if graphic and graphic.group(1) == "includegraphics"
                    else None
                )
                blk = Block(
                    kind=kind,
                    text=caption,
                    line=line_of(m.start()),
                    end_line=line_of(end),
                    target=target,
                    extra={"env": env},
                )
                if kind == "table":
                    blk.rows = [
                        [c.strip() for c in clean_text(r).split("&")]
                        for r in body.split("\\\\")
                        if "&" in r
                    ][:64]
                    blk.text = caption
                events.append((m.start(), end, blk))
            elif env in CODE_ENVS:
                events.append(
                    (
                        m.start(),
                        end,
                        Block(
                            kind="code",
                            text=body.strip("\n"),
                            line=line_of(m.start()),
                            end_line=line_of(end),
                            lang=env,
                        ),
                    )
                )
            elif env in MATH_ENVS:
                events.append(
                    (
                        m.start(),
                        end,
                        Block(
                            kind="math",
                            text=squash(body)[:300],
                            line=line_of(m.start()),
                            end_line=line_of(end),
                        ),
                    )
                )
            elif env in LIST_ENVS:
                for im in ITEM.finditer(body):
                    nxt = ITEM.search(body, im.end())
                    item_text = clean_text(body[im.end() : (nxt.start() if nxt else len(body))])
                    if item_text:
                        pos = m.end() + im.start()
                        events.append(
                            (
                                pos,
                                pos + 1,
                                Block(
                                    kind="list_item",
                                    text=item_text,
                                    line=line_of(pos),
                                    end_line=line_of(pos),
                                    level=1,
                                ),
                            )
                        )
        # A graphic inside a float belongs to the float: drop the standalone figure block.
        float_spans = [
            (s0, e0) for s0, e0, b in events if b.kind in ("figure", "table") and b.extra.get("env")
        ]
        events = [
            (s0, e0, b)
            for s0, e0, b in events
            if not (
                b.kind == "figure"
                and b.extra.get("command") == "includegraphics"
                and any(fs < s0 < fe for fs, fe in float_spans)
            )
        ]
        events.sort(key=lambda e: (e[0], e[1]))
        # Prose between structural events (only outside code/float/math bodies).
        covered: list[tuple[int, int]] = sorted(
            (s, e)
            for s, e, b in events
            if b.kind in ("code", "figure", "table", "math", "heading") and e > s + 1
        )
        cursor = 0
        prose_spans: list[tuple[int, int]] = []
        for s, e in covered:
            if s > cursor:
                prose_spans.append((cursor, s))
            cursor = max(cursor, e)
        if cursor < len(text):
            prose_spans.append((cursor, len(text)))
        for s, e in prose_spans:
            for para in re.split(r"\n\s*\n", text[s:e]):
                start = text.find(para, s, e) if para.strip() else -1
                if start < 0:
                    continue
                body = clean_text(para)
                if len(body) < 2 or body.startswith("\\"):
                    continue
                if BEGIN.match(para.strip()) or para.strip().startswith("\\end"):
                    continue
                events.append(
                    (
                        start,
                        start + len(para),
                        Block(
                            kind="paragraph",
                            text=body,
                            line=line_of(start),
                            end_line=line_of(start + len(para) - 1),
                        ),
                    )
                )
        events.sort(key=lambda e: (e[0], 0 if e[2].kind == "heading" else 1, e[1]))
        tree.blocks.extend(b for _, _, b in events)
        if tree.title is None:
            first = next((b for b in tree.blocks if b.kind == "heading"), None)
            if first:
                tree.title = first.text
        return tree
