"""Everything the Complete Atlas needs: code, documents, and every link between them, in one drawing.

The same parts feed the Complete Atlas page (from the finished index) and the live build in the
ContextMAX window (sent as events while the build runs), so the live drawing ends exactly as the
page draws it. Positions are worked out by atlas.js from this data alone; nothing here moves.

Code is drawn per module (with its functions on demand), documents per lifecycle stage. Lines:
calls between modules, documents that name code, and the links between documents (cited titles,
quoted numbers, shared values, conflicts, the same part of the code).
"""
from __future__ import annotations

import os
from collections import Counter

from contextmax import util
from contextmax.code.common import module_dirs

CONFIDENCE = {"one": 0, "some": 1, "strong": 2}
SHOWN = 4                       # names listed with a link; the documents page and the files hold all of them


def stage_names(proj, core: list[dict]) -> list[str]:
    """The lifecycle stages that hold documents, in the project's own order."""
    order = list(proj.vocabulary.get("stages") or [])
    present = {d["stage"] for d in core}
    return [s for s in order if s in present] + sorted(present - set(order))


HDL_ROLES = {"rtl": "product", "testbench": "test"}


def code_part(proj, functions: bool = True, portable: bool = False) -> dict:
    """Code bases, their modules (with module-to-module calls) and their functions. VHDL counts as code
    too: its modules join the others, an entity placing another is a call, and entities are the functions."""
    targets, modules, calls = [], [], []
    fn = {"m": [], "n": [], "q": [], "f": [], "l": [], "c": [], "k": [], "r": []}
    files, fcalls = [], []
    mod_index: dict[tuple[str, str], int] = {}
    for t in proj.code_targets:
        base = proj.code_dir / t["name"]
        if not (base / "module-list.json").exists():
            continue
        ti = len(targets)
        targets.append({"name": t["name"], "label": t["label"], "root": "" if portable else t["root"]})
        table = util.load_json(base / "module-list.json", default={}) or {}
        dirs = module_dirs(base)
        hdl = util.load_json(base / "hdl-modules.json", default={}) or {}
        entities = util.load_jsonl(base / "hdl-entities.jsonl") if hdl else []
        hdl_files = {name: len({e["file"] for e in entities if e.get("module") == name}) for name in hdl}
        for name in sorted(set(table) | set(hdl)):
            m, h = table.get(name) or {}, hdl.get(name) or {}
            langs = list(m.get("languages") or []) + (["VHDL"] if h else [])
            mod_index[(t["name"], name)] = len(modules)
            modules.append([ti, name, m.get("functions_count", 0) + h.get("entities_count", 0),
                            m.get("files_count", 0) + hdl_files.get(name, 0), ", ".join(langs), dirs.get(name, "")])
        for name in sorted(set(table) | set(hdl)):
            into = Counter((table.get(name) or {}).get("calls_into") or {})
            into.update((hdl.get(name) or {}).get("needs") or {})          # placing another module's entities
            for other, n in sorted(into.items()):
                if (t["name"], other) in mod_index:
                    calls.append([mod_index[(t["name"], name)], mod_index[(t["name"], other)], n])
        if not functions:
            continue
        offset = len(fn["m"])
        file_ids: dict[str, int] = {}
        for f in util.load_jsonl(base / "function-list.jsonl"):
            if f["file"] not in file_ids:
                file_ids[f["file"]] = len(files)
                files.append([ti, f["file"]])
            fn["m"].append(mod_index.get((t["name"], f["module"]), -1))
            fn["n"].append(f["name"])
            fn["q"].append(f.get("qualname") or "")
            fn["f"].append(file_ids[f["file"]])
            fn["l"].append(f["first_line"])
            fn["c"].append(f.get("callers_count", 0))
            fn["k"].append(f.get("calls_count", 0))
            fn["r"].append(f.get("role", "product"))
        fcalls += [[offset + a, offset + b] for a, b in util.load_json(base / "call-pairs.json", default=[]) or []]
        entity_id: dict[str, int] = {}
        for e in entities:
            if e["file"] not in file_ids:
                file_ids[e["file"]] = len(files)
                files.append([ti, e["file"]])
            entity_id.setdefault(e["name"].lower(), len(fn["m"]))
            fn["m"].append(mod_index.get((t["name"], e.get("module")), -1))
            fn["n"].append(e["name"])
            fn["q"].append("")
            fn["f"].append(file_ids[e["file"]])
            fn["l"].append(e.get("line", 0))
            fn["c"].append(e.get("parents_count", 0))
            fn["k"].append(e.get("children_count", 0))
            fn["r"].append(HDL_ROLES.get(e.get("role"), e.get("role") or "product"))
        for place in util.load_json(base / "hdl-tree.json", default=[]) or []:
            a, b = entity_id.get(place["parent"].lower()), entity_id.get(place["child"].lower())
            if a is not None and b is not None:
                fcalls.append([a, b])
    return {"targets": targets, "modules": modules, "calls": calls, "functions": fn, "files": files, "fcalls": fcalls}


def module_index(code: dict) -> dict[tuple[str, str], int]:
    names = [t["name"] for t in code["targets"]]
    return {(names[m[0]], m[1]): i for i, m in enumerate(code["modules"])}


def docs_part(proj, core: list[dict], portable: bool = False) -> dict:
    """The documents of the map, in the map's own order, with what the drawer shows about each."""
    stages = stage_names(proj, core)
    at = {s: i for i, s in enumerate(stages)}
    roots = {f.name: f.path for f in proj.folders}
    docs = {"k": [], "t": [], "s": [], "x": [], "e": [], "fo": [], "rel": [], "p": [], "tx": [], "cp": []}
    for d in core:
        docs["k"].append(d["key"])
        docs["t"].append(d["title"])
        docs["s"].append(at[d["stage"]])
        docs["x"].append(1 if d.get("kind") == "spreadsheet" else 0)
        docs["e"].append(d.get("ext") or "")
        docs["fo"].append(d.get("folder") or "")
        docs["rel"].append(d.get("relative_path") or "")
        path = None
        if not portable and roots.get(d.get("folder")) and d.get("relative_path"):
            path = os.path.normpath(os.path.join(roots[d["folder"]], d["relative_path"]))
        docs["p"].append(path)
        docs["tx"].append(None if portable else d.get("cached_text"))
        docs["cp"].append(d.get("copies", 1))
    return {"stages": stages, "docs": docs}


def entity_modules(code: dict) -> dict[tuple[str, str], int]:
    """(code base, entity name in lower case) -> module, for the VHDL entities a document names."""
    names = [t["name"] for t in code["targets"]]
    fn, out = code["functions"], {}
    for f, mi in enumerate(fn["m"]):
        if mi >= 0 and code["files"][fn["f"][f]][1].lower().endswith((".vhd", ".vhdl")):
            out.setdefault((names[code["modules"][mi][0]], fn["n"][f].lower()), mi)
    return out


def code_link_rows(edges: list[dict], doc_at: dict[str, int], mods: dict[tuple[str, str], int],
                   entities: dict[tuple[str, str], int] | None = None) -> list[list]:
    """Document names code: [document, module, how many names, confidence, first names, primary]. A VHDL
    entity is filed under its code base; here it goes to the module that holds the entity."""
    rows = []
    for e in edges:
        d = doc_at.get(e["document_key"])
        if d is None:
            continue
        names = e.get("key_names") or e.get("symbols") or []
        for t in e.get("targets") or []:
            mi = mods.get((t, e["module"]))
            if mi is not None:
                top = [[s["sym"], s["kind"], s["n"]] for s in names[:6]]
                rows.append([d, mi, e["weight"], CONFIDENCE.get(e["confidence"], 0), top, 1 if e.get("primary") else 0])
                continue
            by_module: dict[int, list] = {}
            for s in e.get("symbols") or []:
                m = (entities or {}).get((t, s["sym"].lower())) if s["kind"] == "entity" else None
                if m is not None:
                    by_module.setdefault(m, []).append(s)
            for m, found in sorted(by_module.items()):
                top = [[s["sym"], s["kind"], s["n"]] for s in found[:6]]
                weight = len(found)
                rows.append([d, m, weight, 2 if weight >= 5 else 1 if weight >= 2 else 0, top, 1 if e.get("primary") else 0])
    return rows


VALUE_OUTCOMES = ("match", "mismatch", "unit unknown", "units differ")


def value_code_rows(rows: list[dict], doc_at: dict[str, int], mods: dict[tuple[str, str], int]) -> list[list]:
    """A document's value found in the code: [document, module, outcome, value name, the document's value,
    code name, the code's value, note], one per document and code value."""
    out = []
    for r in rows:
        c = r["code"]
        mi = mods.get((c["target"], c.get("module")))
        if mi is None:
            continue
        code_value = f"{c['value']} {c.get('unit') or ''}".strip()
        for d in r["documents"]:
            at = doc_at.get(d["doc_ref"])
            if at is not None:
                out.append([at, mi, VALUE_OUTCOMES.index(r["outcome"]), r.get("label") or "", r["doc_shown"], c["name"],
                            code_value, r["note"]])
    return out


def link_detail(e: dict):
    """What a line between two documents says, kept short: the drawer shows it when the line is clicked."""
    k = e["kind"]
    if k == "cites":
        return e.get("count")
    if k == "quotes":
        return e.get("doc_number")
    if k == "samepart":
        return e.get("module")
    if k in ("shares", "anchor"):
        return [e.get("shared_count", 0), e.get("agree_count", 0), e.get("differ_count", 0),
                (e.get("shared") or [])[:SHOWN], (e.get("differ") or [])[:SHOWN]]
    if k == "differs":
        return (e.get("values") or [])[:SHOWN]
    return None


def doc_link_rows(edges: list[dict], doc_at: dict[str, int], kinds: list[str]) -> dict:
    """Links between documents, column by column: kind, from, to, detail."""
    out = {"k": [], "a": [], "b": [], "d": []}
    for e in edges:
        a, b = doc_at.get(e["from"]), doc_at.get(e["to"])
        if a is None or b is None:
            continue
        if e["kind"] not in kinds:
            kinds.append(e["kind"])
        out["k"].append(kinds.index(e["kind"]))
        out["a"].append(a)
        out["b"].append(b)
        out["d"].append(link_detail(e))
    return out


def function_doc_rows(proj, code: dict, doc_at: dict[str, int]) -> list[list]:
    """Which documents name which function: [function, document, times named]."""
    by_name: dict[tuple[int, str], list[int]] = {}
    names = [t["name"] for t in code["targets"]]
    for fid, mi in enumerate(code["functions"]["m"]):
        ti = code["modules"][mi][0] if mi >= 0 else -1
        by_name.setdefault((ti, code["functions"]["n"][fid]), []).append(fid)
    cdocs = util.load_json(proj.documents_dir / "links" / "code-to-doc.json", default={}) or {}
    rows = []
    for ti, t in enumerate(names):
        for name, entries in sorted(((cdocs.get(t) or {}).get("functions") or {}).items()):
            for fid in by_name.get((ti, name), []):
                for x in entries:
                    d = doc_at.get(x["key"])
                    if d is not None:
                        rows.append([fid, d, x.get("n", 1)])
    return rows


# == the live build: the same parts, sent while the build makes them ==

LINKS_PER_EVENT = 5000


def live_code(proj) -> None:
    code = code_part(proj, functions=False, portable=True)      # the drawing needs no paths, like the documents
    util.live("code", targets=code["targets"], modules=code["modules"], calls=code["calls"])


def live_documents(proj, core: list[dict]) -> None:
    util.live("stages", **docs_part(proj, core, portable=True))


def live_code_links(proj, core: list[dict], edges: list[dict]) -> None:
    doc_at = {d["key"]: i for i, d in enumerate(core)}
    code = code_part(proj)
    rows = code_link_rows(edges, doc_at, module_index(code), entity_modules(code))
    for i in range(0, len(rows), LINKS_PER_EVENT):
        util.live("dcode", rows=rows[i:i + LINKS_PER_EVENT])
    util.live("placed")


def live_document_links(core: list[dict], edges: list[dict]) -> None:
    doc_at = {d["key"]: i for i, d in enumerate(core)}
    for i in range(0, len(edges), LINKS_PER_EVENT):
        kinds: list[str] = []
        part = doc_link_rows(edges[i:i + LINKS_PER_EVENT], doc_at, kinds)
        util.live("links", kinds=kinds, **part)


def build(proj, portable: bool = False) -> dict:
    dm = proj.documents_dir
    core = util.load_jsonl(dm / "doc-list.jsonl")
    code = code_part(proj, portable=portable)
    mods = module_index(code)
    dpart = docs_part(proj, core, portable)
    doc_at = {k: i for i, k in enumerate(dpart["docs"]["k"])}
    kinds = ["quotes", "cites", "shares", "anchor", "differs", "samepart"]
    links = doc_link_rows(util.load_jsonl(dm / "links" / "between-docs.jsonl"), doc_at, kinds)
    dcode = code_link_rows(util.load_jsonl(dm / "links" / "doc-to-code.jsonl"), doc_at, mods, entity_modules(code))
    fdocs = function_doc_rows(proj, code, doc_at)
    vcode = value_code_rows(util.load_jsonl(dm / "links" / "value-to-code.jsonl"), doc_at, mods)
    per_kind = Counter(links["k"])
    counts = {"modules": len(code["modules"]), "functions": len(code["functions"]["m"]), "module_calls": len(code["calls"]),
              "function_calls": len(code["fcalls"]), "documents": len(core), "code_links": len(dcode), "value_links": len(vcode),
              "links": {k: per_kind[i] for i, k in enumerate(kinds) if per_kind[i]}}
    return {"project": proj.name, **code, **dpart, "dcode": dcode, "vcode": vcode, "fdocs": fdocs, "kinds": kinds, "links": links,
            "counts": counts}
