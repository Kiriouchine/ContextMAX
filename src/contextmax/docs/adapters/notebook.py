# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`notebook-v1`: Jupyter notebooks. Markdown cells go through the Markdown adapter; code cells
become code blocks tagged with the kernel language (analysed by the code tiers as in-document
code); outputs are summarised, never embedded."""

from __future__ import annotations

import json

from contextmax.docs.adapters.markdown import MarkdownAdapter
from contextmax.docs.base import Block, DocumentTree, ExtractionError


class NotebookAdapter:
    id = "notebook-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        try:
            nb = json.loads(data.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ExtractionError(f"not a valid notebook: {exc.__class__.__name__}") from exc
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        meta = nb.get("metadata", {}) if isinstance(nb, dict) else {}
        language = (meta.get("kernelspec", {}) or {}).get("language") or (meta.get("language_info", {}) or {}).get("name")
        tree.metadata["kernel_language"] = language
        tree.metadata["line_model"] = "cell sources concatenated; lines count from 1 across cells"
        cells = nb.get("cells", []) if isinstance(nb, dict) else []
        line = 1
        md = MarkdownAdapter()
        for index, cell in enumerate(cells, start=1):
            source = cell.get("source", "")
            text = "".join(source) if isinstance(source, list) else str(source)
            n_lines = max(text.rstrip("\n").count("\n") + 1, 1)
            kind = cell.get("cell_type")
            tree.blocks.append(Block(kind="cell", text="", line=line, end_line=line + n_lines - 1, extra={"cell": index, "cell_type": kind}))
            if kind == "markdown":
                sub = md.extract(key, text.encode("utf-8"))
                for block in sub.blocks:
                    block.line += line - 1
                    block.end_line += line - 1
                    tree.blocks.append(block)
                if tree.title is None and sub.title:
                    tree.title = sub.title
            elif kind == "code":
                tree.blocks.append(Block(kind="code", text=text, lang=language, line=line, end_line=line + n_lines - 1,
                                         extra={"cell": index, "execution_count": cell.get("execution_count")}))
                outputs = cell.get("outputs") or []
                if outputs:
                    kinds = sorted({o.get("output_type", "?") for o in outputs})
                    tree.blocks.append(Block(kind="paragraph", text=f"[{len(outputs)} output(s): {', '.join(kinds)}]",
                                             line=line, end_line=line + n_lines - 1))
            else:
                tree.blocks.append(Block(kind="paragraph", text=text.strip(), line=line, end_line=line + n_lines - 1))
            line += n_lines
        tree.metadata["n_cells"] = len(cells)
        if tree.title is None:
            tree.title = key.rsplit("/", 1)[-1]
        return tree
