"""Everything a document page needs.

The grid is the document map's own: lifecycle stages left to right (each with a lane for its
workbooks), and three rows: documents that name code, documents about a part of the code,
and stand-alone documents. Positions are decided here, so the picture never moves.
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict

from contextmax import util

ROW_H, SUB_W, COLUMN_SPACING, TIER_SPACING, LIST_ROWS = 44, 220, 64, 110, 30
SHEET_LANE = " · sheets"
TIERS = [("Names code", "names functions or constants of the code"),
         ("About a part of the code", "a subsystem's subject, but no code names"),
         ("Stand-alone", "process, project, general")]
LINK_KINDS = ["cites", "quotes", "shares", "anchor", "differs", "samepart"]
VALUES_SHOWN = 8                # values listed on a "differs" link; value-conflicts.jsonl holds every one


def build(proj, portable: bool = False) -> dict:
    dm = proj.documents_dir
    core = util.load_jsonl(dm / "doc-list.jsonl")
    dc = util.load_jsonl(dm / "links" / "doc-to-code.jsonl")
    dd = util.load_jsonl(dm / "links" / "between-docs.jsonl")
    structure = {r["key"]: r for r in util.load_jsonl(dm / "doc-outlines.jsonl")}
    summary = util.load_json(dm / "overview.json", default={}) or {}
    stages = summary.get("stages") or sorted({d["stage"] for d in core})
    per_code = defaultdict(list)
    for e in dc:
        per_code[e["document_key"]].append(e)
    # its values in the code: [value name, its value here, code name, the code's value, outcome, note, code base]
    in_code = defaultdict(list)
    for r in util.load_jsonl(dm / "links" / "value-to-code.jsonl"):
        c = r["code"]
        for d in r["documents"]:
            in_code[d["doc_ref"]].append([r.get("label") or "", r["doc_shown"], c["name"], f"{c['value']} {c.get('unit') or ''}".strip(),
                                          r["outcome"], r["note"], c.get("target_label") or c["target"]])
    roots = {f.name: f.path for f in proj.folders}

    modules_with_code = {d.get("main_module") for d in core if d.get("linked_code")}
    named_by_code = set()
    keys_with_code = {d["key"] for d in core if d.get("linked_code")}
    for e in dd:
        if e["kind"] == "samepart":
            if e["from"] in keys_with_code:
                named_by_code.add(e["to"])
            if e["to"] in keys_with_code:
                named_by_code.add(e["from"])
    tier = {}
    for d in core:
        if d.get("linked_code"):
            tier[d["key"]] = 0
        elif d["key"] in named_by_code or (d.get("about_module") and d.get("about_module") in modules_with_code) \
                or d.get("about_module"):
            tier[d["key"]] = 1
        else:
            tier[d["key"]] = 2

    # columns: each stage, then its workbook lane; empty lanes dropped
    def column_of(d):
        return d["stage"] + (SHEET_LANE if d["kind"] == "spreadsheet" else "")
    used = {column_of(d) for d in core}
    columns = [c for s in stages for c in (s, s + SHEET_LANE) if c in used]
    columns += sorted(used - set(columns))
    cells = defaultdict(list)
    for d in core:
        cells[(column_of(d), tier[d["key"]])].append(d)
    for docs in cells.values():
        docs.sort(key=lambda d: (d.get("main_module") or d.get("about_module") or d.get("module") or "~", d["title"].lower()))
    subcols = {c: max(1, max(-(-len(cells.get((c, t), [])) // LIST_ROWS) for t in range(3))) for c in columns}
    colx, x = {}, 0
    for c in columns:
        colx[c] = x
        x += subcols[c] * SUB_W + COLUMN_SPACING
    rows_by_tier = {t: max((min(len(cells.get((c, t), [])), LIST_ROWS) for c in columns), default=0) for t in range(3)}
    tier_top, y = {}, 0
    for t in range(3):
        tier_top[t] = y
        if rows_by_tier[t]:
            y += rows_by_tier[t] * ROW_H + TIER_SPACING
    width, height = x - COLUMN_SPACING, y

    modules = sorted({m for d in core for m in ([d.get("main_module")] + [d.get("about_module")]) if m})
    nodes, id_by_key = [], {}
    for c in columns:
        for t in range(3):
            for i, d in enumerate(cells.get((c, t), [])):
                nid = len(nodes)
                id_by_key[d["key"]] = nid
                nodes.append(_doc_node(nid, d, c, t, colx[c] + (i // LIST_ROWS) * SUB_W,
                                   tier_top[t] + (i % LIST_ROWS) * ROW_H, per_code, structure, roots, portable))
                nodes[-1]["vc"] = in_code.get(d["key"], [])
    edges = []
    for e in dd:
        if e["from"] in id_by_key and e["to"] in id_by_key:
            item = {"a": id_by_key[e["from"]], "b": id_by_key[e["to"]], "k": e["kind"]}
            for f in ("module", "doc_number", "count", "shared_count", "agree_count", "differ_count", "shared", "differ"):
                if e.get(f) not in (None, [], ""):
                    item[f] = e[f]
            if e.get("values"):
                item["values"] = e["values"][:VALUES_SHOWN]
            edges.append(item)
    headers = [{"label": c.replace(SHEET_LANE, ""), "sheet": c.endswith(SHEET_LANE), "x": colx[c],
                "w": subcols[c] * SUB_W} for c in columns]
    tier_headers = [{"label": TIERS[t][0], "sub": TIERS[t][1], "y": tier_top[t], "h": rows_by_tier[t] * ROW_H}
                    for t in range(3) if rows_by_tier[t]]
    variables, statements = _variables(proj, id_by_key)
    code_targets = [{"name": t["name"], "label": t["label"]} for t in proj.code_targets
                    if (proj.code_dir / t["name"] / "function-list.jsonl").exists()]
    return {"nodes": nodes, "edges": edges, "headers": headers, "tiers": tier_headers, "modules": modules,
            "width": width, "height": height, "variables": variables, "statements": statements,
            "code_targets": code_targets, "link_kinds": LINK_KINDS,
            "counts": {"docs": len(nodes), "linked_code": sum(1 for n in nodes if n["code"]),
                       "links": dict(sorted(Counter(e["k"] for e in edges).items()))}}


def _doc_node(nid, d, column, tier, x, y, per_code, structure, roots, portable) -> dict:
    s = structure.get(d["key"]) or {}
    params = []
    seen = set()
    for p in sorted(s.get("values") or [], key=lambda p: (0 if p.get("label_norm") else 1,
                                                              0 if p.get("unit_norm") else 1)):
        key = (p.get("label_norm") or "", p.get("value_norm"), p.get("unit_norm"))
        if key in seen:
            continue
        seen.add(key)
        params.append([p.get("label") or "", p.get("value"), p.get("unit_norm") or "", p.get("label_norm") or ""])
        if len(params) == 12:
            break
    abs_path = None
    if not portable and roots.get(d.get("folder")) and d.get("relative_path"):
        abs_path = os.path.normpath(os.path.join(roots[d["folder"]], d["relative_path"]))
    return {
        "id": nid, "key": d["key"], "t": d["title"], "dt": d.get("doc_title") or "", "st": d["stage"],
        "col": column, "tier": tier, "kind": d["kind"], "ext": d.get("ext") or "",
        "mod": d.get("main_module") or d.get("module") or "", "topic": d.get("about_module") or "",
        "copies": d.get("copies", 1), "copy_list": d.get("copy_list", [])[:8], "reason": d.get("reason"),
        "folder": d.get("folder"), "rel": d.get("relative_path"), "pages": d.get("pages"), "chars": d.get("chars"),
        "x": x, "y": y,
        "code": [{"m": e["module"], "w": e["weight"], "c": e["confidence"], "t": e["targets"],
                  "top": [[s2["sym"], s2["kind"], s2["n"]] for s2 in e["key_names"][:8]]}
                 for e in sorted(per_code.get(d["key"], []), key=lambda e: (-e["weight"], e["module"]))],
        "nh": s.get("headings_count", 0), "nr": s.get("requirements_count", 0), "np": s.get("values_count", 0),
        "heads": (s.get("headings") or [])[:14],
        "reqs": [[r["text"][:200], r.get("ids") or []] for r in (s.get("requirements") or [])[:5]],
        "params": params,
        "path": abs_path,          # the window, or a contextmax-open: link, opens it (opener.py)
        "text": None if portable else d.get("cached_text"),
    }


def _variables(proj, id_by_key) -> tuple[list, list]:
    """Named values stated in more than one document: the comparison that matters."""
    by_var = defaultdict(dict)
    shown = {}
    rank = {"cell_entry": 0, "computed_value": 1, "prose_value": 2, "formula_constant": 3}
    for r in util.load_jsonl(proj.documents_dir / "params.jsonl"):
        v = r.get("label_norm") or ""
        nid = id_by_key.get(r["doc_ref"])
        if not v or nid is None or r["origin"] == "formula_constant":
            continue
        cand = (rank.get(r["origin"], 9), r["value_shown"] + (" " + r["unit_norm"] if r["unit_norm"] else ""),
                r["value_norm"] + "|" + r["unit_norm"], r.get("sheet") or "", r.get("cell") or "")
        if nid not in by_var[v] or cand < by_var[v][nid]:
            by_var[v][nid] = cand
        shown.setdefault(v, r.get("label") or v)
    names = sorted(v for v, hits in by_var.items() if len(hits) > 1)
    variables = [[shown[v], v] for v in names]
    index = [[[nid, c[1], c[2], (c[3] + "!" + c[4]) if c[3] else ""] for nid, c in sorted(by_var[v].items())] for v in names]
    return variables, index
