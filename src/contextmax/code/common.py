"""What every language reader shares: line numbers, modules, roles, and the files a code map holds.

A reader turns source files into function records whose calls are already resolved to the
keys of other records. From there on C, Python and MATLAB are treated alike: the call graph,
the name lookup, the module table and the guide are written once, here.
"""
from __future__ import annotations

import bisect
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from contextmax import util

# Folders that only group code and say nothing about what it does; they are passed over when a
# module is named, so `src/motor/x.c` belongs to module `motor`.
CONTAINER_DIRS = {"code", "inc", "include", "lib", "libs", "source", "sources", "src"}
_ROLE_DIRS = (
    ("test", {"test", "tests", "testbench", "testing", "tb", "unittest", "unittests"}, re.compile(r"_tests?\.\w+$")),
    ("stub", {"fake", "fakes", "mock", "mocks", "stub", "stubs"}, re.compile(r"_stubs?\.\w+$")),
    ("doc", {"doc", "docs", "example", "examples"}, None),
)
_NEWLINE = re.compile(r"\n")
_SPACES = re.compile(r"[\r\n\t ]+")


def line_offsets(text: str) -> list[int]:
    """Where each line starts, for line_at()."""
    return [0, *(m.end() for m in _NEWLINE.finditer(text))]


def line_at(starts: list[int], offset: int) -> int:
    return bisect.bisect_right(starts, offset)


def squash_ws(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def role_for(rel: str) -> str:
    """What a file is for, read from its path: product, test, stub or doc."""
    *folders, name = rel.lower().split("/")
    for role, dirs, name_rule in _ROLE_DIRS:
        if any(f in dirs for f in folders) or (role == "test" and name.startswith("test_")) \
                or (name_rule is not None and name_rule.search(name)):
            return role
    return "product"


def module_depth(rels: list[str]) -> int:
    """How many folder levels name a module in this code base: the smallest depth (up to three)
    that splits the code into at least four modules. A flat code base gets one module per file."""
    return next((depth for depth in (1, 2, 3) if len({module_for(r, depth) for r in rels}) >= 4), 0)


def module_for(rel: str, depth: int) -> str:
    if depth == 0:
        parts = rel.rsplit(".", 1)[0].split("/")
    else:
        parts = rel.split("/")[:-1]
        if not parts:
            return "(top)"
    while len(parts) > 1 and parts[0].lower() in CONTAINER_DIRS:
        parts = parts[1:]
    return "/".join(parts if depth == 0 else parts[:depth])


def first_sentence(text: str, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    m = re.search(r"(?<=[.!?])\s", text)
    if m and m.start() < limit:
        return text[: m.start()]
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def leading_comment(raw_lines: list[str], first_line: int, prefixes=("//", "/*", "*", "--", "#", "%")) -> str:
    """The comment block right above a definition, as one sentence."""
    i = first_line - 2
    block: list[str] = []
    while i >= 0:
        s = raw_lines[i].strip()
        if not s:
            if block:
                break
            i -= 1
            continue
        if s.startswith(prefixes) or s.endswith("*/"):
            block.append(s)
            i -= 1
            continue
        break
    block.reverse()
    text = " ".join(re.sub(r"^(/\*+|\*+/?|//+|--+|#+|%+)\s?", "", b).replace("*/", "") for b in block)
    return first_sentence(text)


def _number_and_link(defs: list[dict]) -> tuple[list[list[int]], Counter, int]:
    """Ids in file and line order, then both directions of every call. Returns (call pairs,
    names called outside these folders, how many calls could not be followed)."""
    defs.sort(key=lambda d: (d["file"], d["first_line"], d["name"]))
    id_of = {}
    for number, record in enumerate(defs):
        record["id"] = number
        id_of[record["key"]] = number
    pairs, outside, unknown = [], Counter(), 0
    for record in defs:
        record["callee_ids"], record["calls"] = [], []
        for key in record.pop("call_keys"):
            callee = id_of.get(key)
            if callee is not None and callee not in record["callee_ids"]:
                record["callee_ids"].append(callee)
                record["calls"].append(defs[callee]["name"])
                pairs.append([record["id"], callee])
        record["ambiguous"] = [[name, sorted(id_of[k] for k in keys if k in id_of)]
                               for name, keys in record.get("ambiguous", [])]
        outside.update(record.get("external_calls", []))
        unknown += len(record.get("indirect_calls", []))
    callers = defaultdict(set)
    for caller, callee in pairs:
        callers[callee].add(caller)
    for record in defs:
        record["caller_ids"] = sorted(callers.get(record["id"], ()))
        record["callers_count"] = len(record["caller_ids"])
        record["calls_count"] = len(record["callee_ids"])
        record.pop("key", None)
    return pairs, outside, unknown


def _module_table(defs: list[dict], files: dict, pairs: list[list[int]], includes: dict) -> tuple[dict, dict]:
    """Per module: size, languages, the modules it calls into, includes and its most-called functions."""
    module_files = defaultdict(list)
    for rel, info in files.items():
        module_files[info["module"]].append(rel)
    for record in defs:
        module_files.setdefault(record["module"], [])
    calls_between: dict[str, Counter] = defaultdict(Counter)
    for caller, callee in pairs:
        if defs[caller]["module"] != defs[callee]["module"]:
            calls_between[defs[caller]["module"]][defs[callee]["module"]] += 1
    table = {}
    for name in sorted(module_files):
        members = [d for d in defs if d["module"] == name]
        product = [d for d in members if d["role"] == "product"]
        busiest = sorted(product, key=lambda d: (-d["callers_count"], d["name"]))[:12]
        table[name] = {
            "name": name,
            "files_count": len(module_files[name]),
            "functions_count": len(members),
            "product_functions_count": len(product),
            "languages": sorted({d["lang"] for d in members}),
            "calls_into": dict(sorted(calls_between.get(name, {}).items())),
            "includes_from": dict(sorted(includes.get(name, {}).items())),
            "most_called": [{"name": d["name"], "callers": d["callers_count"], "file": d["file"],
                             "line": d["first_line"]} for d in busiest],
        }
    return table, calls_between


def write_map(out: Path, target: dict, defs: list[dict], files: dict, extras: dict) -> dict:
    """Number the functions, link both directions of the call graph, and write the code map.

    `defs` carry `key` and `call_keys`, already resolved by their reader. Ids follow file and
    line order, so they are the same on every run.
    """
    out.mkdir(parents=True, exist_ok=True)
    pairs, outside, unknown = _number_and_link(defs)
    modules, calls_between = _module_table(defs, files, pairs, extras.get("module_includes", {}))
    entry = sorted((d for d in defs if d["role"] == "product" and d["callers_count"] == 0),
                   key=lambda d: (d["module"], d["name"], d["file"]))
    lookup = defaultdict(list)
    for d in defs:
        place = {"file": d["file"], "line": d["first_line"], "module": d["module"], "role": d["role"],
                 "lang": d["lang"], "id": d["id"]}
        if d["lang"] == "C++":
            place["qualname"] = d["qualname"]           # documents may name it as Class::method
        lookup[d["name"]].append(place)

    util.save_jsonl(out / "function-list.jsonl", defs)
    util.save_json(out / "file-list.json", dict(sorted(files.items())))
    util.save_json(out / "call-pairs.json", pairs)
    util.save_json(out / "name-lookup.json", dict(sorted(lookup.items())))
    util.save_json(out / "declarations.json", dict(sorted(extras.get("prototypes", {}).items())))
    util.save_json(out / "unmatched-calls.json", sorted(outside.items(), key=lambda kv: (-kv[1], kv[0])))
    util.save_json(out / "macro-map.json", dict(sorted(extras.get("macro_map", {}).items())))
    util.save_json(out / "indirect-calls.json", [{"id": d["id"], "name": d["name"], "file": d["file"],
                                                  "calls": d["indirect_calls"]} for d in defs if d.get("indirect_calls")])
    util.save_json(out / "module-list.json", modules)

    overview = {
        "target": target["name"],
        "label": target.get("label", target["name"]),
        "languages": dict(sorted(Counter(d["lang"] for d in defs).items())),
        "files_count": len(files),
        "functions_count": len(defs),
        "product_functions_count": sum(1 for d in defs if d["role"] == "product"),
        "test_functions_count": sum(1 for d in defs if d["role"] == "test"),
        "call_edges_count": len(pairs),
        "modules_count": len(modules),
        "unresolved_call_names_count": len(outside),
        "ambiguous_calls_count": sum(len(d["ambiguous"]) for d in defs),
        "indirect_calls_count": unknown,
        "macro_aliases_resolved_count": len(extras.get("macro_map", {})),
        "entry_points_count": len(entry),
        "module_depth": extras.get("module_depth", 1),
        "modules": {name: m["functions_count"] for name, m in modules.items()},
    }
    if extras.get("cpp"):
        overview["cpp"] = extras["cpp"]
    util.save_json(out / "overview.json", overview)
    util.save_text(out / "code-guide.md", _guide(target, overview, modules, defs, calls_between, entry))
    return overview


def _by_count(counts: dict) -> str:
    return ", ".join(f"{k} ({v})" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _guide(target: dict, ov: dict, modules: dict, defs: list[dict], calls_between: dict, entry: list[dict]) -> str:
    """The code map as one page a person or an AI agent can read from top to bottom."""
    languages = ", ".join(f"{k} {v}" for k, v in ov["languages"].items()) or "none"
    out = [f"# Code guide: {target.get('label', target['name'])}", "",
           "Built by ContextMAX from the source files alone (no compiler, no AI). Every function below has "
           "its file and line range, so it can be opened directly.", "",
           "| | |", "|---|---|",
           f"| Languages | {languages} |",
           f"| Files | {ov['files_count']} |",
           f"| Functions | {ov['functions_count']} ({ov['product_functions_count']} product, "
           f"{ov['test_functions_count']} test) |",
           f"| Calls followed | {ov['call_edges_count']} |",
           f"| Modules | {ov['modules_count']} |",
           f"| Calls not followed | {ov['indirect_calls_count']} through a pointer or an object; "
           f"{ov['ambiguous_calls_count']} to a name defined more than once (one was chosen, the others are "
           "listed under `ambiguous` in `function-list.jsonl`) |", ""]
    cpp = ov.get("cpp")
    if cpp:
        unread = cpp["files_with_syntax_errors_count"]
        out[-1:-1] = [f"| C++ | {cpp['files_count']} files read by {cpp['parser'] or 'nothing: ' + cpp['problem']}"
                      f"{'; ' + str(unread) + ' with text the parser could not fully read (listed in overview.json)' if unread else ''}. "
                      "A method called on an object whose type the text does not state is not followed: it is listed "
                      "in `indirect-calls.json` with the name of the method (every definition of that name is in "
                      "`name-lookup.json`); a virtual method lists the methods that override it under `overridden_by` |"]
    node = {name: f"M{n}" for n, name in enumerate(sorted(modules))}
    out += ["## How the modules call each other", "", "```mermaid", "flowchart LR"]
    out += [f'  {node[name]}["{name}"]' for name in sorted(modules)]
    for name in sorted(calls_between):
        out += [f"  {node[name]} -- {n} --> {node[other]}"
                for other, n in sorted(calls_between[name].items(), key=lambda kv: (-kv[1], kv[0]))]
    out += ["```", "", "## Modules", "", "| Module | Files | Functions | of which product | Calls functions in |",
            "|---|--:|--:|--:|---|"]
    out += [f"| {name} | {m['files_count']} | {m['functions_count']} | {m['product_functions_count']} | "
            f"{_by_count(m['calls_into'])} |" for name, m in sorted(modules.items())]
    out += ["", "## Functions", ""]
    for name in sorted({d["module"] for d in defs}):
        out += [f"### Module {name}", ""]
        if modules[name]["includes_from"]:
            out += ["Includes headers of: " + _by_count(modules[name]["includes_from"]), ""]
        mine = sorted((d for d in defs if d["module"] == name), key=lambda d: (d["file"], d["first_line"]))
        for rel in sorted({d["file"] for d in mine}):
            out.append(f"`{rel}`")
            for d in (d for d in mine if d["file"] == rel):
                signature = f"{d['ret'] + ' ' if d.get('ret') else ''}{d.get('qualname') or d['name']}({', '.join(d['params'] or [])})"
                out.append(f"- L{d['first_line']}-{d['last_line']} `{signature}` [{d['role']}]: "
                           f"called by {d['callers_count']}, calls {d['calls_count']}")
                if d.get("doc"):
                    out.append(f"  - {d['doc']}")
                if d["calls"]:
                    out.append(f"  - calls {', '.join(sorted(set(d['calls'])))}")
            out.append("")
    out += ["## Entry points", "",
            "Product functions that nothing in these folders calls by name: main loops, interrupt handlers, "
            "callbacks, public interfaces, or code that is no longer used. A function that is only reached "
            "through a pointer is listed here too.", ""]
    for name in sorted({d["module"] for d in entry}):
        out.append(f"- {name}: " + ", ".join(f"`{d['name']}` ({d['file']} L{d['first_line']})"
                                            for d in entry if d["module"] == name))
    out += ["", "## Reading the other files (for an AI agent)", "",
            "| File | Holds |", "|---|---|",
            "| `name-lookup.json` | each name with every definition: `{file, line, module, role, lang, id}` |",
            "| `function-list.jsonl` | one function per line: `callee_ids`, `caller_ids`, `external_calls`, "
            "`indirect_calls`, `ambiguous`; the whole graph |",
            "| `call-pairs.json` | `[from_id, to_id]` for every call, for any walk through the graph |",
            "| `module-list.json`, `file-list.json` | per module and per file |",
            "| `unmatched-calls.json` | names called here but defined outside these folders, with counts |",
            "| `indirect-calls.json` | calls whose target the text cannot tell; an impact answer must mention them |",
            "", "Open a function with its `file` and `first_line`, under the code base's folder."]
    return "\n".join(out)


def module_dirs(base: Path) -> dict[str, str]:
    """The folder each module's files share, relative to the code base ("" for the code base's own folder):
    what "Open its folder" opens. From the code map's file list, and the VHDL entities' files."""
    files: dict[str, list[str]] = defaultdict(list)
    for rel, info in (util.load_json(base / "file-list.json", default={}) or {}).items():
        files[info.get("module") or ""].append(rel)
    for e in util.load_jsonl(base / "hdl-entities.jsonl"):
        if e.get("module") and e.get("file"):
            files[e["module"]].append(e["file"])
    out = {}
    for module, rels in files.items():
        dirs = [r.rsplit("/", 1)[0] if "/" in r else "" for r in rels]
        common = dirs[0].split("/") if dirs[0] else []
        for d in dirs[1:]:
            parts = d.split("/") if d else []
            k = 0
            while k < min(len(common), len(parts)) and common[k] == parts[k]:
                k += 1
            common = common[:k]
        out[module] = "/".join(common)
    return out


def list_sources_by(root: Path, groups: dict[str, set[str]], skip_dirs: set[str]) -> dict[str, list[tuple[str, str]]]:
    """list_sources for several sets of extensions, in one walk through the folders: the same lists."""
    found: dict[str, list] = {name: [] for name in groups}
    for folder, subfolders, names in os.walk(root):
        if ".contextmax-skip" in names:
            subfolders[:] = []
            continue
        subfolders[:] = sorted(d for d in subfolders if d not in skip_dirs)
        for n in names:
            ext = os.path.splitext(n)[1].lower()
            hits = [g for g, extensions in groups.items() if ext in extensions]
            if hits:
                pair = (os.path.join(folder, n), util.rel_key(os.path.join(folder, n), root))
                for g in hits:
                    found[g].append(pair)
    return {g: sorted(pairs, key=lambda pair: pair[1]) for g, pairs in found.items()}


def list_sources(root: Path, extensions: set[str], skip_dirs: set[str]) -> list[tuple[str, str]]:
    """(full, rel) for every file with one of these extensions, in the order of rel."""
    found = []
    for folder, subfolders, names in os.walk(root):
        if ".contextmax-skip" in names:
            subfolders[:] = []
            continue
        subfolders[:] = sorted(d for d in subfolders if d not in skip_dirs)
        found += [(os.path.join(folder, n), util.rel_key(os.path.join(folder, n), root))
                  for n in names if os.path.splitext(n)[1].lower() in extensions]
    return sorted(found, key=lambda pair: pair[1])
