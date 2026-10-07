"""The parameters page: every named value, where each document states it, and whether they agree.

A value is found by its name. The verdict compares the numbers only, so a unit cell that is
missing next to one occurrence is not reported as a disagreement. Spreadsheet cells carry
their formula, and the cells a formula reads are included so the page can walk the chain
back to the constants without opening the workbook.
"""
from __future__ import annotations

import re
from collections import defaultdict

from contextmax import util
from contextmax.docs import params as P

ROW_BUDGET = 40_000
MAX_SHEET_CELLS = 60_000
CELL_ADDRESS_RE = re.compile(r"(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_.]*))!)?\$?([A-Z]{1,3})\$?(\d{1,7})")


def build(proj) -> dict:
    core = {d["key"]: d for d in util.load_jsonl(proj.documents_dir / "doc-list.jsonl")}
    rows = util.load_jsonl(proj.documents_dir / "params.jsonl")
    by_var = defaultdict(list)
    cells = defaultdict(dict)
    shown = {}
    for r in rows:
        if r.get("sheet") and r.get("cell") and r["origin"] in ("cell_entry", "computed_value"):
            cells[r["file_key"]][f"{r['sheet']}!{r['cell']}"] = [r["value_shown"], r["unit_norm"], r.get("label") or "", r.get("formula") or ""]
        lab = r.get("label_norm") or ""
        if P.says_nothing(lab) or r["origin"] == "formula_constant":
            continue
        node = core.get(r["doc_ref"], {})
        where = f"{r['sheet']}!{r['cell']}" if r.get("sheet") and r.get("cell") else ""
        title = node.get("title", r["doc_ref"])
        if r["file_key"] != r["doc_ref"]:
            title += f" (copy: {r['file_key']})"
        by_var[lab].append([title, r["doc_ref"], node.get("stage", ""), r["value_shown"],
                            r["unit_norm"], where, r["origin"], r.get("formula") or "",
                            1 if r.get("hidden") else 0, r["value_norm"], r["file_key"],
                            "" if where else (r.get("context") or "")[:160]])
        shown.setdefault(lab, r.get("label") or lab)
    variables = []
    for lab, rs in by_var.items():
        docs = {x[1] for x in rs}
        values = {x[9] for x in rs}
        variables.append([shown[lab], lab, len(docs), len(rs), "match" if len(values) == 1 else "differ"])
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
            "stats": {"rows_count": len(rows), "named_variables_count": len(variables), "shared_count": sum(1 for v in variables if v[2] > 1),
                      "differ_count": sum(1 for v in variables if v[2] > 1 and v[4] == "differ"), "truncated": truncated}}
