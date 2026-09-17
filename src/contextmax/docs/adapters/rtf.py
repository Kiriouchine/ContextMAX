# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`rtf-v1`: a small Rich Text control-word reader. Paragraphs, headings from the stylesheet
("heading N" styles) or from short all-bold paragraphs, hyperlink fields, tables row per line,
code page and Unicode escapes; pictures, fonts, colours and metadata groups are skipped."""

from __future__ import annotations

import re

from contextmax.docs.adapters.common import split_number, squash
from contextmax.docs.base import Block, DocumentTree, ExtractionError

TOKEN = re.compile(rb"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([^\\{}]+)", re.S)
SKIP_GROUPS = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header", "footer", "headerl", "headerr",
               "footerl", "footerr", "listtable", "listoverridetable", "revtbl", "rsidtbl", "xmlnstbl", "themedata",
               "colorschememapping", "latentstyles", "datastore", "generator", "mmathPr", "wgrffmtfilter", "shppict", "nonshppict",
               "userprops", "protusertbl", "datafield", "xmlopen", "xmlclose", "bkmkstart", "bkmkend", "pntext",
               "background", "sp", "sn", "sv", "shp", "shpinst"}
HEADING_STYLE = re.compile(r"heading\s*(\d)", re.I)
CODEPAGES = {437: "cp437", 850: "cp850", 1250: "cp1250", 1251: "cp1251", 1252: "cp1252", 1253: "cp1253", 1254: "cp1254",
             1255: "cp1255", 1256: "cp1256", 1257: "cp1257", 1258: "cp1258", 932: "cp932", 936: "gbk", 949: "cp949", 950: "big5"}


def _stylesheet(data: bytes) -> dict[int, str]:
    """`\\sN` -> style name from the stylesheet group, read with a tiny brace scanner."""
    start = data.find(rb"{\stylesheet")
    if start < 0:
        return {}
    depth = 0
    end = start
    for i in range(start, len(data)):
        if data[i : i + 1] == b"{":
            depth += 1
        elif data[i : i + 1] == b"}":
            depth -= 1
            if depth == 0:
                end = i
                break
    names: dict[int, str] = {}
    for m in re.finditer(rb"\{\\s(\d+)[^;{}]*?\s([^\\{};]+);", data[start:end]):
        names[int(m.group(1))] = m.group(2).decode("latin-1").strip()
    return names


class RtfAdapter:
    id = "rtf-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        if not data.lstrip().startswith(b"{\\rtf"):
            raise ExtractionError("not an RTF file (no {\\rtf header)")
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        styles = _stylesheet(data)
        m = re.search(rb"\\ansicpg(\d+)", data[:2000])
        codepage = CODEPAGES.get(int(m.group(1)), "cp1252") if m else "cp1252"
        stack: list[dict[str, object]] = [{"skip": False, "bold": False, "uc": 1}]
        para: list[str] = []
        para_bold: list[bool] = []
        para_style: int | None = None
        para_line = 1
        line = 1
        in_row = False
        row_cells: list[str] = []
        skip_chars = 0  # fallback characters that follow a \uN escape
        pending_url: str | None = None
        blocks = tree.blocks

        def flush() -> None:
            nonlocal para, para_bold, para_style
            text = squash("".join(para))
            if text:
                name = styles.get(para_style or -1, "")
                hm = HEADING_STYLE.search(name)
                all_bold = para_bold and all(para_bold) and len(text.split()) <= 12 and not text.endswith(".")
                if hm:
                    number, clean = split_number(text)
                    blocks.append(Block(kind="heading", text=clean, level=int(hm.group(1)), number=number, line=para_line, end_line=line))
                elif name.lower() == "title":
                    blocks.append(Block(kind="title", text=text, line=para_line, end_line=line))
                    if tree.title is None:
                        tree.title = text
                        tree.metadata["title_source"] = "title-style"
                elif all_bold:
                    number, clean = split_number(text)
                    blocks.append(Block(kind="heading", text=clean, level=1, number=number, line=para_line, end_line=line, extra={"bold_heading": True}))
                else:
                    blocks.append(Block(kind="paragraph", text=text, line=para_line, end_line=line))
            para, para_bold, para_style = [], [], None

        for m in TOKEN.finditer(data):
            word, arg, hexbyte, escaped, brace, text = m.groups()
            state = stack[-1]
            if brace == b"{":
                stack.append(dict(state))
                continue
            if brace == b"}":
                if len(stack) > 1:
                    stack.pop()
                continue
            if word is not None:
                name = word.decode("ascii")
                if state.pop("star", False) and name != "fldinst":
                    state["skip"] = True  # {\*\...}: an ignorable destination we do not understand
                    continue
                if name == "fldinst":
                    state["fldinst"] = True  # field instructions: only HYPERLINK is read
                    continue
                if name == "bin":
                    state["skip"] = True  # binary data follows inside this group; nothing readable
                    continue
                if state["skip"]:
                    if name == "par" or name == "row":
                        pass
                    continue
                if name in SKIP_GROUPS:
                    state["skip"] = True
                    continue
                if name == "par" or name == "sect" or name == "page":
                    line += 0
                    flush()
                    para_line = line
                elif name == "line":
                    para.append(" ")
                elif name == "tab":
                    para.append("\t")
                elif name == "cell":
                    row_cells.append(squash("".join(para)))
                    para, para_bold = [], []
                elif name == "row":
                    in_row = True
                    blocks.append(Block(kind="table", rows=[list(row_cells)], line=para_line, end_line=line))
                    row_cells = []
                    para, para_bold = [], []
                elif name == "b":
                    state["bold"] = arg is None or int(arg) != 0
                elif name == "s" and arg is not None:
                    para_style = int(arg)
                elif name == "uc" and arg is not None:
                    state["uc"] = int(arg)
                elif name == "u" and arg is not None:
                    code = int(arg)
                    para.append(chr(code + 65536 if code < 0 else code))
                    para_bold.append(bool(state["bold"]))
                    skip_chars = int(state["uc"])  # drop the fallback characters that follow \uN
                elif name in ("emdash", "endash", "bullet", "lquote", "rquote", "ldblquote", "rdblquote"):
                    para.append({"emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022", "lquote": "\u2018", "rquote": "\u2019",
                                 "ldblquote": "\u201c", "rdblquote": "\u201d"}[name])
                elif name == "field":
                    pending_url = None
                elif name == "fldrslt":
                    pass
                continue
            if state["skip"]:
                continue
            if hexbyte is not None:
                if skip_chars:
                    skip_chars -= 1
                    continue
                try:
                    para.append(bytes.fromhex(hexbyte.decode("ascii")).decode(codepage, errors="replace"))
                except LookupError:
                    para.append("?")
                para_bold.append(bool(state["bold"]))
                continue
            if escaped is not None:
                if escaped == b"*":
                    state["star"] = True  # decided by the control word that follows
                    continue
                if escaped in (b"{", b"}", b"\\"):
                    para.append(escaped.decode("ascii"))
                    para_bold.append(bool(state["bold"]))
                elif escaped in (b"\n", b"\r"):
                    flush()
                    para_line = line
                elif escaped == b"~":
                    para.append("\u00a0")
                elif escaped == b"-":
                    pass  # optional hyphen
                elif escaped == b"_":
                    para.append("-")
                continue
            if text is not None:
                line += text.count(b"\n")
                chunk = text.replace(b"\r", b"").replace(b"\n", b"")
                if chunk:
                    decoded = chunk.decode(codepage, errors="replace")
                    if skip_chars:
                        decoded, skip_chars = decoded[skip_chars:], 0
                        if not decoded:
                            continue
                    if state.get("fldinst"):
                        hm = re.search(r'HYPERLINK\s+"([^"]+)"', decoded)
                        if hm:
                            pending_url = hm.group(1)
                            blocks.append(Block(kind="link", text=pending_url, target=pending_url, line=line, end_line=line))
                        continue  # other field instructions (PAGE, TOC, ...) are not text
                    para.append(decoded)
                    para_bold.append(bool(state["bold"]))
        flush()
        del in_row
        if tree.title is None:
            first = next((b for b in blocks if b.kind in ("title", "heading") and b.text), None)
            tree.title = first.text if first else key.rsplit("/", 1)[-1]
        return tree
