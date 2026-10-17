"""The parameters page: every named value, where each document states it, whether they agree, and what the
code says of it.

A value is found by its name. The verdict compares the numbers only, so a unit cell that is
missing next to one occurrence is not reported as a disagreement. Spreadsheet cells carry
their formula, and the cells a formula reads are included so the page can walk the chain
back to the constants without opening the workbook. Every row cites where it is in one format
(citations.py) and carries its line, so the window can show that line of the document's text.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from contextmax import citations, util
from contextmax.docs import params as P

ROW_BUDGET = 40_000
MAX_SHEET_CELLS = 60_000
CELL_ADDRESS_RE = re.compile(r"(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_.]*))!)?\$?([A-Z]{1,3})\$?(\d{1,7})")


def _code_side(proj, portable: bool) -> dict:
    """Per value name (or, for a value matched by its number, per code name), what the code says of it."""
    roots = {t["name"]: t["root"] for t in proj.code_targets}
    out = defaultdict(list)
    for r in util.load_jsonl(proj.documents_dir / "links" / "value-to-code.jsonl"):
        c = r["code"]
        editor = None
        if not portable and roots.get(c["target"]):
            full = str(Path(roots[c["target"]]) / c["file"]).replace("\\", "/")
            editor = "vscode://file/" + quote(full, safe="/:") + f":{c['line']}"
        key = r["label_norm"] or f"code:{c['name']}"
        out[key].append([r["outcome"], r["note"], r["matched_by"], c["name"], c["value"], c.get("unit") or "",
                         c.get("unit_from") or "", c.get("target_label") or c["target"], c["file"], c["line"], editor,
                         r["doc_shown"], r["candidates_count"], c.get("unit_note") or "", c.get("comment") or "",
                         [[d["doc_ref"], d.get("line_no")] for d in r["documents"]]])
    return out


_WORST = ("mismatch", "units differ", "unit unknown", "match")


def build(proj, portable: bool = False) -> dict:
    core = {d["key"]: d for d in util.load_jsonl(proj.documents_dir / "doc-list.jsonl")}
    texts = {r["key"]: r.get("cached_text") for r in util.load_jsonl(proj.documents_dir / "text-index.jsonl")}
    rows = util.load_jsonl(proj.documents_dir / "params.jsonl")
    code = _code_side(proj, portable)
    by_number = {(d[0], d[1]): key for key, cs in code.items() if key.startswith("code:") for c in cs for d in c[15]}
    by_var = defaultdict(list)
    cells = defaultdict(dict)
    shown = {}
    for r in rows:
        if r.get("sheet") and r.get("cell") and r["origin"] in ("cell_entry", "computed_value"):
            cells[r["file_key"]][f"{r['sheet']}!{r['cell']}"] = [r["value_shown"], r["unit_norm"], r.get("label") or "", r.get("formula") or ""]
        lab = r.get("label_norm") or ""
        if not lab and (r["doc_ref"], r.get("line_no")) in by_number:
            lab = by_number[(r["doc_ref"], r["line_no"])]             # a value the code has, found by its number
        elif P.says_nothing(lab) or r["origin"] == "formula_constant":
            continue
        node = core.get(r["doc_ref"], {})
        where = f"{r['sheet']}!{r['cell']}" if r.get("sheet") and r.get("cell") else ""
        title = node.get("title", r["doc_ref"])
        if r["file_key"] != r["doc_ref"]:
            title += f" (copy: {r['file_key']})"
        by_var[lab].append([title, r["doc_ref"], node.get("stage", ""), r["value_shown"],
                            r["unit_norm"], where, r["origin"], r.get("formula") or "",
                            1 if r.get("hidden") else 0, r["value_norm"], r["file_key"],
                            (r.get("sentence") or r.get("context") or "")[:200],
                            citations.value(dict(r, stage=node.get("stage") or r.get("stage")), title),
                            r.get("line_no"), None if portable else texts.get(r["file_key"]), r.get("symbol") or ""])
        shown.setdefault(lab, r.get("label") or (lab[5:] + " (found by its number)" if lab.startswith("code:") else lab))
    variables = []
    for lab, rs in by_var.items():
        docs = {x[1] for x in rs}
        values = {x[9] for x in rs}
        outcomes = {c[0] for c in code.get(lab, [])}
        variables.append([shown[lab], lab, len(docs), len(rs), "match" if len(values) == 1 else "differ",
                          next((w for w in _WORST if w in outcomes), "")])
    variables.sort(key=lambda v: (-v[2], -v[3], v[1]))
    kept, total, truncated = {}, 0, False
    for v in variables:
        rs = sorted(by_var[v[1]], key=lambda x: (x[0].lower(), x[5], x[3]))
        if total + len(rs) > ROW_BUDGET and kept:
            truncated = True
            continue
        kept[v[1]] = rs
        total += len(rs)
    # cells that formulas of the kept rows read, so a trace can walk back without the workbook
    trace_docs = sorted({x[10] for rs in kept.values() for x in rs if x[7]})
    trace, cells_count = {}, 0
    for doc in trace_docs:
        if cells_count + len(cells[doc]) > MAX_SHEET_CELLS:
            truncated = True
            continue
        trace[doc] = cells[doc]
        cells_count += len(cells[doc])
    return {"variables": [v for v in variables if v[1] in kept], "rows": kept, "cells": trace,
            "code": {k: v for k, v in code.items() if k in kept},
            "stats": {"rows_count": len(rows), "named_variables_count": len(variables), "shared_count": sum(1 for v in variables if v[2] > 1),
                      "differ_count": sum(1 for v in variables if v[2] > 1 and v[4] == "differ"), "truncated": truncated,
                      "in_code_count": sum(1 for v in variables if v[5]),
                      "code_mismatch_count": sum(1 for v in variables if v[5] in ("mismatch", "units differ"))}}
