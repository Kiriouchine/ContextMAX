"""Everything a code page needs, with every deterministic coordinate already decided.

  bubbles   modules, then a module's functions, laid out live by physics
  drafting  modules as blocks holding their functions as circles, blocks in call order
  metro     each module a coloured line; stations are its functions in call order; a link
            between lines is a call from one module into another, like a change of trains
  zoom      code bases, then modules, then one function with its callers and callees
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path

from contextmax import util
from contextmax.views.layout import layered, ranks

CELL = 30                 # drafting: one function circle per cell
BLOCK_PAD = 14
BLOCK_HEAD = 40
MAX_IN_BLOCK = 400        # drafting: a module with more functions shows its 400 most-called
METRO_GAP_X = 74
METRO_GAP_Y = 96
METRO_STATIONS = 24       # stations per line; the rest are counted, not drawn


def radius(callers: int) -> float:
    return round(min(13.0, 4.0 + 2.6 * math.log2(1 + callers)), 1)


def build(proj, target: dict, portable: bool = False) -> dict:
    d = proj.code_dir / target["name"]
    summary = util.load_json(d / "overview.json", default={}) or {}
    funcs = util.load_jsonl(d / "function-list.jsonl")
    modules_json = util.load_json(d / "module-list.json", default={}) or {}
    docs_of_code = (util.load_json(proj.documents_dir / "links" / "code-to-doc.json", default={}) or {}).get(target["name"], {})
    files = sorted({f["file"] for f in funcs})
    file_idx = {f: i for i, f in enumerate(files)}
    mod_names = sorted(modules_json) or sorted({f["module"] for f in funcs})
    mod_idx = {m: i for i, m in enumerate(mod_names)}

    functions = []
    for f in funcs:
        functions.append({
            "id": f["id"], "n": f["name"], "q": f.get("qualname") or f["name"], "m": mod_idx[f["module"]],
            "r": f["role"], "k": f.get("kind", "function"), "lang": f["lang"], "f": file_idx[f["file"]],
            "l": f["first_line"], "e": f["last_line"], "c": f["callers_count"], "o": f["calls_count"],
            "d": f.get("doc") or "", "sig": _signature(f), "x": f.get("external_calls", [])[:30],
            "nx": len(f.get("external_calls", [])), "ind": f.get("indirect_calls", [])[:12],
            "amb": f.get("ambiguous", []), "rad": radius(f["callers_count"]),
        })
    calls = util.load_json(d / "call-pairs.json", default=[]) or []
    mod_edges = Counter()
    for a, b in calls:
        ma, mb = functions[a]["m"], functions[b]["m"]
        if ma != mb:
            mod_edges[(ma, mb)] += 1
    modules = []
    for m in mod_names:
        mj = modules_json.get(m, {})
        modules.append({"id": mod_idx[m], "name": m, "nf": mj.get("functions_count", 0),
                        "np": mj.get("product_functions_count", 0), "files": mj.get("files_count", 0),
                        "docs": [[x["title"], x["stage"], x["confidence"], x["key"]] for x in docs_of_code.get("modules", {}).get(m, [])][:12]})
    docs_for = {}
    by_name = defaultdict(list)
    for f in functions:
        by_name[f["n"]].append(f["id"])
    for name, docs in (docs_of_code.get("functions") or {}).items():
        for fid in by_name.get(name, []):
            docs_for[str(fid)] = [[x["title"], x["stage"], x["confidence"], x["key"]] for x in docs[:8]]

    data = {
        "target": {"name": target["name"], "label": target.get("label", target["name"]),
                   "languages": summary.get("languages", {}), "root": "" if portable else target["root"]},
        "summary": {k: summary.get(k) for k in ("files_count", "functions_count", "product_functions_count", "test_functions_count",
                                                  "call_edges_count", "modules_count", "unresolved_call_names_count",
                                                  "ambiguous_calls_count", "indirect_calls_count", "entry_points_count")},
        "modules": modules, "functions": functions, "files": files, "calls": calls,
        "mod_edges": [[a, b, n] for (a, b), n in sorted(mod_edges.items())],
        "docs_for": docs_for,
        "unresolved": (util.load_json(d / "unmatched-calls.json", default=[]) or [])[:40],
    }
    data["drafting"] = _drafting(modules, functions, data["mod_edges"])
    data["metro"] = _metro(modules, functions, calls, data["mod_edges"])
    data["zoom"] = _zoom(modules, data["mod_edges"])
    vh = _vhdl(d)
    if vh:
        data["vhdl"] = vh
    return data


def _signature(f: dict) -> str:
    params = ", ".join(f.get("params") or [])
    name = f.get("qualname") or f["name"]
    if f["lang"] == "Python":
        return f"{'class' if f.get('kind') == 'class' else 'def'} {name}({params})" + (f" -> {f['ret']}" if f.get("ret") else "")
    if f["lang"] == "MATLAB":
        outs = f.get("ret") or ""
        return f"function {'[' + outs + '] = ' if outs else ''}{name}({params})"
    return f"{f.get('ret') + ' ' if f.get('ret') else ''}{name}({params})"


def _drafting(modules, functions, mod_edges) -> dict:
    per_module = defaultdict(list)
    for f in functions:
        per_module[f["m"]].append(f)
    sizes, inner, hidden = {}, {}, {}
    for m in modules:
        fs = sorted(per_module.get(m["id"], []), key=lambda f: (-f["c"], f["n"], f["id"]))
        shown = sorted(fs[:MAX_IN_BLOCK], key=lambda f: (f["f"], f["l"]))
        hidden[m["id"]] = len(fs) - len(shown)
        n = max(1, len(shown))
        cols = max(4, math.ceil(math.sqrt(n * 1.8)))
        rows = math.ceil(n / cols)
        w = cols * CELL + 2 * BLOCK_PAD
        h = BLOCK_HEAD + rows * CELL + BLOCK_PAD
        w = max(w, 12 + 8 * len(m["name"]))
        sizes[m["id"]] = (w, h)
        inner[m["id"]] = [(f["id"], BLOCK_PAD + (i % cols) * CELL + CELL // 2, BLOCK_HEAD + (i // cols) * CELL + CELL // 2)
                          for i, f in enumerate(shown)]
    lay = layered([m["id"] for m in modules], [(a, b) for a, b, _ in mod_edges], sizes, gap_x=150, gap_y=56)
    blocks, circles = [], {}
    for m in modules:
        x, y, w, h = lay["pos"][m["id"]]
        blocks.append({"m": m["id"], "x": x, "y": y, "w": w, "h": h, "hidden": hidden[m["id"]]})
        for fid, cx, cy in inner[m["id"]]:
            circles[str(fid)] = [x + cx, y + cy]
    return {"blocks": blocks, "circles": circles, "width": lay["width"], "height": lay["height"]}


def _metro(modules, functions, calls, mod_edges) -> dict:
    """Lines in module call order; stations are the functions that matter on that line."""
    cross = defaultdict(set)
    for a, b in calls:
        if functions[a]["m"] != functions[b]["m"]:
            cross[a].add(b)
            cross[b].add(a)
    rank, _, _ = ranks([f["id"] for f in functions], [tuple(c) for c in calls])
    mod_lay = layered([m["id"] for m in modules], [(a, b) for a, b, _ in mod_edges], default=(1, 1), gap_x=1, gap_y=1)
    mod_order = sorted(modules, key=lambda m: (mod_lay["rank"].get(m["id"], 0) if mod_lay.get("rank") else 0,
                                               mod_lay["pos"].get(m["id"], (0, 0))[1] if mod_lay["pos"] else 0, m["name"]))
    per_module = defaultdict(list)
    for f in functions:
        if f["r"] == "test":
            continue
        per_module[f["m"]].append(f)
    lines, station_x = [], {}
    for li, m in enumerate(mod_order):
        fs = per_module.get(m["id"], [])
        notable = [f for f in fs if f["id"] in cross]
        rest = sorted((f for f in fs if f["id"] not in cross), key=lambda f: (-f["c"], f["n"]))
        chosen = sorted(notable, key=lambda f: (-len(cross[f["id"]]), -f["c"], f["n"]))[:METRO_STATIONS]
        chosen += rest[: max(0, min(6, METRO_STATIONS - len(chosen)))]
        chosen.sort(key=lambda f: (rank.get(f["id"], 0), f["n"], f["id"]))
        y = 60 + li * METRO_GAP_Y
        x_prev = 120
        stations = []
        for f in chosen:
            x = max(x_prev + METRO_GAP_X, 200 + rank.get(f["id"], 0) * METRO_GAP_X)
            stations.append([f["id"], x])
            station_x[f["id"]] = (x, y)
            x_prev = x
        lines.append({"m": m["id"], "y": y, "stations": stations, "more": len(fs) - len(chosen),
                      "x0": 160, "x1": (stations[-1][1] + 40) if stations else 240})
    links = sorted({(a, b) for a, b in calls if a in station_x and b in station_x
                    and functions[a]["m"] != functions[b]["m"]})
    width = max([ln["x1"] for ln in lines] + [400]) + 120
    return {"lines": lines, "links": [list(x) for x in links], "width": width,
            "height": 120 + len(lines) * METRO_GAP_Y}


def _zoom(modules, mod_edges) -> dict:
    sizes = {m["id"]: (156, 52) for m in modules}
    lay = layered([m["id"] for m in modules], [(a, b) for a, b, _ in mod_edges], sizes, gap_x=90, gap_y=24)
    return {"modules": {str(k): list(v) for k, v in lay["pos"].items()}, "width": lay["width"], "height": lay["height"]}


def _vhdl(d: Path) -> dict | None:
    ents = util.load_jsonl(d / "hdl-entities.jsonl")
    if not ents:
        return None
    names = [e["name"] for e in ents]
    idx = {e["name"].lower(): i for i, e in enumerate(ents)}
    edges = Counter()
    for r in util.load_json(d / "hdl-tree.json", default=[]) or []:
        if r["parent"] in idx and r["child"] in idx:
            edges[(idx[r["parent"]], idx[r["child"]])] += 1
    sizes = {i: (max(120, 9 * len(n) + 24), 40) for i, n in enumerate(names)}
    lay = layered(list(range(len(ents))), list(edges), sizes, gap_x=90, gap_y=18)
    summary = util.load_json(d / "hdl-overview.json", default={}) or {}
    return {"entities": [{"n": e["name"], "m": e["module"], "r": e["role"], "cls": e.get("classification"),
                          "file": e["file"], "line": e["line"], "ports": e["ports_count"], "kids": e["children_count"],
                          "parents": e["parents_count"]} for e in ents],
            "edges": [[a, b, n] for (a, b), n in sorted(edges.items())],
            "pos": {str(k): list(v) for k, v in lay["pos"].items()}, "width": lay["width"], "height": lay["height"],
            "summary": {k: summary.get(k) for k in ("entities_count", "instantiations_count", "hdl_top", "unresolved_instances_count")}}
