"""Lookups an AI (or a person) runs against a built project. Every hit carries where it came from.

    find doc|symbol|callers|callees|impact|module|docs-for|code-for|links
    params   named values: where stated, and whether the documents agree
    sheet    one workbook read live: cells, formulas, a trace to the constants, a row-pairing check
    status   how fresh and complete the index is, and the status line for answers
"""
from __future__ import annotations

import os
import re
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from contextmax import util
from contextmax.catalogue import SKIP_DIR_NAMES
from contextmax.code import c_lang, cpp_lang, matlab_lang, python_lang, vhdl_lang
from contextmax.code.common import list_sources
from contextmax.docs import params as P
from contextmax.docs import sheets

CODE_SUFFIXES = (c_lang.EXTENSIONS | cpp_lang.EXTENSIONS | python_lang.EXTENSIONS | matlab_lang.EXTENSIONS
                 | vhdl_lang.EXTENSIONS)


# == status ==

def status(proj) -> dict:
    m = util.load_json(proj.workspace / "buildinfo.json", default=None)
    if not m:
        return {"built": None, "sync": "not built", "confidence": "Low", "confidence_reason": "not built yet",
                "problems": ["not built yet"]}
    comp = m.get("completeness", {})
    changed = []
    for name, cm in (m.get("code_bases") or {}).items():
        t = next((t for t in proj.code_targets if t["name"] == name), None)
        if not t or not Path(t["root"]).is_dir():
            changed.append(f"{name}: folder not found")
            continue
        files = list_sources(Path(t["root"]), CODE_SUFFIXES, set(SKIP_DIR_NAMES))
        now = util.canonical_hash([[rel, util.hash_file(full)] for full, rel in files])
        if now != cm.get("tree_hash"):
            changed.append(f"code in {name} changed")
    roots = {f.name: f.path for f in proj.folders}
    stale_docs = 0
    for r in util.load_jsonl(proj.documents_dir / "text-index.jsonl"):
        p = Path(roots.get(r["folder"], "")) / r["relative_path"]
        try:
            st = os.stat(p)
        except OSError:
            stale_docs += 1
            continue
        stamp = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")
        if stamp != r.get("file_mtime_utc") or st.st_size != r.get("file_bytes"):
            stale_docs += 1
    if stale_docs:
        changed.append(f"{stale_docs} document(s) changed or moved")
    sync = "in sync" if not changed else "changed since the build"
    conf, reason = comp.get("confidence", "Low"), comp.get("confidence_reason", "")
    if changed and conf == "High":
        conf, reason = "Medium", "sources changed since build"
    return {"built": m.get("built_utc"), "contextmax_version": m.get("contextmax_version"),
            "inputs_hash": m.get("inputs_hash"),
            "outputs_hash": m.get("outputs_hash"), "sync": sync, "changes": changed,
            "confidence": conf, "confidence_reason": reason, "problems": comp.get("problems", []),
            "completeness": comp}


def status_line(proj, s: dict | None = None) -> str:
    s = s or status(proj)
    built = (s.get("built") or "never")[:10]
    reason = " ".join((s.get("confidence_reason") or "").split()[:6])
    return f"- ContextMAX ({proj.slug}): built {built} · {s.get('sync')} · confidence {s.get('confidence')} ({reason})"


# == find ==

def _targets(proj, only: str | None):
    for t in proj.code_targets:
        if only and t["name"] != only:
            continue
        d = proj.code_dir / t["name"]
        if (d / "overview.json").exists():
            yield t, d


def _functions(d: Path) -> list[dict]:
    return util.load_jsonl(d / "function-list.jsonl")


def _fn_hit(t: dict, f: dict) -> dict:
    return {"target": t["name"], "name": f.get("qualname") or f["name"], "kind": f.get("kind"), "lang": f["lang"],
            "role": f["role"], "module": f["module"], "file": f["file"], "line": f["first_line"],
            "last_line": f["last_line"], "cite": f"{f['file']}:{f['first_line']}-{f['last_line']}",
            "path": str(Path(t["root"]) / f["file"]), "callers": f["callers_count"], "calls": f["calls_count"],
            "doc": f.get("doc") or ""}


def _match_fns(funcs: list[dict], q: str) -> list[dict]:
    exact = [f for f in funcs if f["name"] == q or f.get("qualname") == q]
    if exact:
        return exact
    low = q.lower()
    return sorted((f for f in funcs if low in (f.get("qualname") or f["name"]).lower()),
                  key=lambda f: (-f["callers_count"], f["name"]))


def find(proj, what: str, q: str, target: str | None = None, depth: int = 0, limit: int = 30) -> dict:
    if what == "doc":
        return _find_doc(proj, q, limit)
    if what in ("symbol", "callers", "callees", "impact"):
        out = {"query": q, "what": what, "hits": []}
        for t, d in _targets(proj, target):
            funcs = _functions(d)
            for f in _match_fns(funcs, q)[:limit]:
                hit = _fn_hit(t, f)
                if what == "callers":
                    hit["callers_list"] = _walk(funcs, f["id"], "caller_ids", depth or 1, limit, t)
                elif what == "callees":
                    hit["callees_list"] = _walk(funcs, f["id"], "callee_ids", depth or 1, limit, t)
                    hit["outside_calls"] = f.get("external_calls", [])[:40]
                elif what == "impact":
                    hit["impact"] = _impact(funcs, f["id"], depth, t)
                if f.get("indirect_calls"):
                    hit["not_followed"] = f["indirect_calls"][:10]
                if f.get("ambiguous"):
                    hit["ambiguous"] = f["ambiguous"]
                out["hits"].append(hit)
            for name, e in (util.load_json(d / "hdl-name-lookup.json", default={}) or {}).items():
                if what == "symbol" and (name.lower() == q.lower() or (q.lower() in name.lower() and len(q) > 2)):
                    out["hits"].append({"target": t["name"], "name": name, "kind": "VHDL entity", "file": e["file"],
                                        "line": e["line"], "cite": f"{e['file']}:{e['line']}", "module": e["module"],
                                        "role": e["role"], "path": str(Path(t["root"]) / e["file"])})
        out["hits"] = out["hits"][:limit]
        if not out["hits"]:
            out["note"] = "No definition with that name in the mapped code. Check `contextmax status` for code bases not mapped."
        return out
    if what == "module":
        out = {"query": q, "hits": []}
        for t, d in _targets(proj, target):
            for name, m in (util.load_json(d / "module-list.json", default={}) or {}).items():
                if q.lower() in name.lower():
                    out["hits"].append({"target": t["name"], **m})
        return out
    if what in ("docs-for", "code-for", "links"):
        return _cross(proj, what, q, limit)
    raise ValueError(f"unknown lookup {what}")


def _walk(funcs, start, field, depth, limit, t):
    seen, out, queue = {start}, [], deque([(start, 0)])
    while queue:
        n, lvl = queue.popleft()
        if lvl >= depth:
            continue
        for m in funcs[n][field]:
            if m in seen:
                continue
            seen.add(m)
            h = _fn_hit(t, funcs[m])
            h["level"] = lvl + 1
            out.append(h)
            queue.append((m, lvl + 1))
    out.sort(key=lambda h: (h["level"], h["role"] != "product", h["name"]))
    return out[:limit * 4]


def _impact(funcs, start, depth, t) -> dict:
    """Everything that can reach this function through calls the map can see."""
    seen, queue = {start: 0}, deque([start])
    while queue:
        n = queue.popleft()
        if depth and seen[n] >= depth:
            continue
        for c in funcs[n]["caller_ids"]:
            if c not in seen:
                seen[c] = seen[n] + 1
                queue.append(c)
    reached = [funcs[i] for i in seen if i != start]
    prod = [f for f in reached if f["role"] != "test"]
    mods = sorted({f["module"] for f in prod})
    total_indirect = sum(len(f.get("indirect_calls", [])) for f in funcs)
    return {"product_functions": len(prod), "tests": len(reached) - len(prod), "modules": mods,
            "direct_callers": len(funcs[start]["caller_ids"]),
            "entry_points_reached": sorted(f["name"] for f in prod if f["callers_count"] == 0)[:30],
            "list": [{"name": f.get("qualname") or f["name"], "cite": f"{f['file']}:{f['first_line']}", "role": f["role"],
                      "level": seen[f["id"]]} for f in sorted(reached, key=lambda f: (seen[f["id"]], f["name"]))][:200],
            "caveat": (f"{total_indirect} calls in this code base go through pointers or objects and are not followed; "
                       "a caller through a pointer is not in this list.") if total_indirect else
                      "Every call in this code base is a direct call by name."}


def _find_doc(proj, q: str, limit: int) -> dict:
    low = q.lower()
    core = util.load_jsonl(proj.documents_dir / "doc-list.jsonl")
    roots = {f.name: f.path for f in proj.folders}
    hits = []
    for d in core:
        hay = " ".join([d["title"], d.get("doc_title") or "", d["key"], d.get("doc_numbers") or "", d.get("relative_path") or ""]).lower()
        if low in hay:
            hits.append({"title": d["title"], "doc_title": d.get("doc_title"), "key": d["key"], "stage": d["stage"],
                         "folder": d["folder"], "relative_path": d["relative_path"],
                         "path": str(Path(roots.get(d["folder"], "")) / d["relative_path"]),
                         "text": str(proj.documents_dir / d["cached_text"]) if d.get("cached_text") else None,
                         "copies": d.get("copies", 1), "names_code": d.get("linked_code", False)})
    files = []
    if len(hits) < limit:
        for r in util.csv_rows(proj.catalogue_dir / "all-files.csv"):
            if low in (r["Name"] + " " + r["RelativePath"] + " " + r["DocNumbers"]).lower():
                files.append({"name": r["Name"], "folder": r["Folder"], "relative_path": r["RelativePath"], "category": r["Category"],
                              "modified": r["Modified"], "in_cloud": r["OnlineOnly"] == "True",
                              "path": str(Path(roots.get(r["Folder"], "")) / r["RelativePath"])})
                if len(files) >= limit:
                    break
    return {"query": q, "hits": hits[:limit], "other_files": files,
            "note": "hits are mapped documents (text read); other_files are catalogue matches (any file)."}


def _cross(proj, what: str, q: str, limit: int) -> dict:
    low = q.lower()
    if what == "docs-for":
        cd = util.load_json(proj.documents_dir / "links" / "code-to-doc.json", default={}) or {}
        hits = []
        for target, data in cd.items():
            for kind in ("functions", "modules"):
                for name, docs in data.get(kind, {}).items():
                    if name.lower() == low or (kind == "modules" and low in name.lower()):
                        hits.append({"target": target, kind[:-1]: name, "documents": docs[:limit]})
        return {"query": q, "hits": hits}
    core = {d["key"]: d for d in util.load_jsonl(proj.documents_dir / "doc-list.jsonl")}
    keys = [k for k, d in core.items() if low in (d["title"] + " " + k + " " + (d.get("doc_title") or "")).lower()]
    if what == "code-for":
        edges = [e for e in util.load_jsonl(proj.documents_dir / "links" / "doc-to-code.jsonl") if e["document_key"] in keys]
        return {"query": q, "hits": [{"doc": e["document_key"], "module": e["module"], "confidence": e["confidence"],
                                      "names": [s["sym"] for s in e["symbols"][:30]], "targets": e["targets"]} for e in edges]}
    edges = [e for e in util.load_jsonl(proj.documents_dir / "links" / "between-docs.jsonl") if e["from"] in keys or e["to"] in keys]
    return {"query": q, "hits": edges[: limit * 3]}


# == params ==

def params(proj, name=None, compare=False, value=None, exact=None, unit=None, origin=None,
           named_only=False, limit=50) -> dict:
    db = proj.documents_dir / "params.sqlite"
    if not db.exists():
        return {"error": "no value database yet: build with --documents"}
    where, vals = [], []
    if name:
        where.append("pl.label_norm LIKE ?")
        vals.append("%" + P.canon_label(name) + "%")
    if named_only:
        where.append("pl.label_norm <> ''")
    if value is not None or exact is not None:
        field = "e.value_exact_norm" if exact is not None else "e.value_norm"
        where.append(field + "=?")
        vals.append(P.canon_number(exact if exact is not None else value))
    if unit:
        where.append("e.unit_norm=?")
        vals.append(P.canon_unit(unit))
    if origin:
        where.append("e.origin=?")
        vals.append(origin)
    sql = ("SELECT pl.label, pl.label_norm, e.value_shown, e.value_as_written, e.value_norm, e.unit_norm, e.origin, "
           "pl.sheet, pl.cell, pl.formula, pl.hidden, pl.context, s.file_key, s.doc_ref, s.stage, s.folder, s.relative_path "
           "FROM entries e JOIN places pl ON pl.id = e.place JOIN sources s ON s.id = pl.source")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.file_key, e.id"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(sql, vals)]
    finally:
        con.close()
    for r in rows:
        r["where"] = f"{r['sheet']}!{r['cell']}" if r.get("sheet") else "text"
    if not compare:
        return {"query": {"name": name, "value": value, "exact": exact, "unit": unit}, "n": len(rows), "rows": rows[:limit],
                "note": "A bare number matches every place it is written; prefer --name." if (value or exact) and not name else ""}
    groups = defaultdict(list)
    for r in rows:
        if r["origin"] != "formula_constant" and r["label"]:
            groups[r["label_norm"]].append(r)
    out = []
    for _lab, hits in sorted(groups.items(), key=lambda kv: (-len({h["doc_ref"] for h in kv[1]}), kv[0]))[:limit]:
        stated = defaultdict(list)
        for h in hits:
            stated[h["value_norm"]].append(h)
        docs = {h["doc_ref"] for h in hits}
        out.append({"name": hits[0]["label"], "documents": len(docs),
                    "verdict": "match" if len(stated) == 1 else f"{len(stated)} different values",
                    "values": [{"value": g[0]["value_shown"] + (" " + g[0]["unit_norm"] if g[0]["unit_norm"] else ""),
                                "stated_in": [{"document": h["file_key"], "where": h["where"], "found_as": h["origin"],
                                               "formula": h["formula"]} for h in g]}
                               for _, g in sorted(stated.items(), key=lambda kv: -len(kv[1]))]})
    return {"query": {"name": name}, "compare": out,
            "note": "The verdict compares numbers only. Check any value that matters in the original document."}


# == sheet ==

# A cell a formula reads: Budget!B4, 'Error budget'!$C$7, or B4 on the formula's own sheet.
CELL_ADDRESS_RE = re.compile(r"""
    (?: (?: '(?P<s1>[^']+)' | (?P<s2>[0-9A-Za-z_]+) ) ! )?
    (?P<a> [$]? [A-Z]{1,3} [$]? [0-9]{1,7} )
    (?! [(0-9] )                                    # LOG10( is a function, not a cell
""", re.VERBOSE)
# A number typed into a formula: not the tail of a name or an address, not a function's name.
NUMBER_PATTERN = re.compile(r"""
    (?<! [$._0-9A-Za-z] )
    [0-9]+ (?: [.] [0-9]+ )?
    (?! [0-9]* \s* [(] )
""", re.VERBOSE)
# A formula that only repeats one other cell: =B4 or ='Error budget'!$C$7.
_ONE_CELL_FORMULA = re.compile(r"= \s* (?: (?: '[^']+' | [0-9A-Za-z_]+ ) ! )? [$]? [A-Z]{1,3} [$]? [0-9]{1,7} \s*",
                               re.VERBOSE)


def _refs(formula: str, sheet: str) -> list[str]:
    out = []
    for m in CELL_ADDRESS_RE.finditer(formula or ""):
        s = m.group("s1") or m.group("s2") or sheet
        a = f"{s}!{m.group('a').replace('$', '')}"
        if a not in out:
            out.append(a)
    return out


def _literals(formula: str) -> list[str]:
    body = CELL_ADDRESS_RE.sub(" ", re.sub(r'"[^"]*"', " ", formula or ""))
    return list(dict.fromkeys(NUMBER_PATTERN.findall(body)))


def sheet(proj, key=None, path=None, sheet=None, cell=None, trace=None, lint=False) -> int:
    """Read one workbook live. Values from the file itself; formulas of an old .xls from its .xlsx copy."""
    if key:
        row = next((r for r in util.load_jsonl(proj.documents_dir / "text-index.jsonl") if r["key"] == key), None)
        if not row:
            print(f"no document with key {key}")
            return 3
        roots = {f.name: f.path for f in proj.folders}
        path = str(Path(roots[row["folder"]]) / row["relative_path"])
    if not path or not os.path.exists(path):
        print(f"not found: {path}")
        return 3
    xlsx_copy = None
    if path.lower().endswith(".xls"):
        entry = (util.load_json(proj.path("staging", "xlsx-copies", "copies.json"), default={}) or {}).get(path.lower())
        if entry and os.path.exists(entry.get("converted", "")):
            xlsx_copy = entry["converted"]
    data = sheets.cells(path, sheet, xlsx_copy)
    print(f"workbook: {path}\nreader: {data['engine']} | sheets: {', '.join(data['sheets'])}")
    if data["linked_workbooks"]:
        print("other workbooks referenced: " + ", ".join(data["linked_workbooks"]))
    cells_by_ref = {f"{c['sheet']}!{c['addr']}": c for c in data["cells"]}

    def describe(c):
        s = f"{c['sheet']}!{c['addr']} = {c['value']}" + (" [hidden]" if c["hidden"] else "")
        if c["formula"]:
            s += f"  {{{c['formula']}}}"
            lits = _literals(c["formula"])
            if lits:
                s += "   constants: " + ", ".join(lits)
        return s

    def resolve(a):
        return a if "!" in a else f"{sheet or data['sheets'][0]}!{a}"

    if trace:
        start = resolve(trace)
        if start not in cells_by_ref:
            print(f"cell {start} not found")
            return 3
        seen, q = set(), deque([(start, 0)])
        while q:
            a, depth = q.popleft()
            if a in seen:
                continue
            seen.add(a)
            c = cells_by_ref.get(a)
            if not c:
                print("  " * depth + f"{a} (empty or text)")
                continue
            print("  " * depth + describe(c))
            if c["formula"] and depth < 8:
                for r in _refs(c["formula"], c["sheet"]):
                    if r not in seen:
                        q.append((r, depth + 1))
        return 0
    if lint:
        single = {}
        for c in data["cells"]:
            f = c["formula"]
            if f and _ONE_CELL_FORMULA.fullmatch(f):
                single[f"{c['sheet']}!{c['addr']}"] = _refs(f, c["sheet"])[0]
        by_rc = {(c["sheet"], c["row"], c["col"]): c for c in data["cells"]}
        found = 0
        for c in sorted(data["cells"], key=lambda c: (c["sheet"], c["row"], c["col"])):
            me = f"{c['sheet']}!{c['addr']}"
            right = by_rc.get((c["sheet"], c["row"], c["col"] + 1))
            if me not in single or not right:
                continue
            rk = f"{right['sheet']}!{right['addr']}"
            if rk not in single:
                continue
            row_a = int(re.sub(r"\D", "", single[me].split("!")[-1]))
            row_b = int(re.sub(r"\D", "", single[rk].split("!")[-1]))
            if row_a != row_b:
                found += 1
                print(f"CROSSED ROWS? {me} reads {single[me]} but {rk} reads {single[rk]}: the label and the value "
                      "come from different rows")
        print(f"{found} suspicious row(s)")
        return 0
    for c in data["cells"]:
        if cell and resolve(cell) != f"{c['sheet']}!{c['addr']}":
            continue
        print(describe(c))
    return 0
