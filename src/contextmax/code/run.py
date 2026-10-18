"""Map every code base of a project: C, C++, Python and MATLAB into one call graph, VHDL into its hierarchy."""
from __future__ import annotations

import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from contextmax import parallel, util
from contextmax.catalogue import SKIP_DIR_NAMES
from contextmax.code import c_lang, cpp_lang, matlab_lang, python_lang, values, vhdl_lang
from contextmax.code.common import list_sources_by, module_depth, write_map
from contextmax.project import Project

READERS = [("C", c_lang), ("Python", python_lang), ("MATLAB", matlab_lang)]


def _header_is_cpp(full: str) -> bool:
    """One .h file: C++ or C (a piece of parallel work)."""
    return cpp_lang.is_cpp_header(util.load_text(full))


def _module_includes(file_info: dict) -> dict:
    """Which modules include headers of which other modules, over the C and C++ files together."""
    headers = c_lang.EXTENSIONS - {".c"} | cpp_lang.HEADER_EXTENSIONS
    header_module = {os.path.basename(rel): fi["module"] for rel, fi in sorted(file_info.items())
                     if fi.get("lang") in ("C", "C++") and fi["ext"] in headers}
    included: dict[str, Counter] = defaultdict(Counter)
    for _rel, fi in sorted(file_info.items()):
        if fi.get("lang") not in ("C", "C++"):
            continue
        for name in fi["includes"]:
            other = header_module.get(os.path.basename(name))
            if other and other != fi["module"]:
                included[fi["module"]][other] += 1
    return {m: dict(c) for m, c in included.items()}


def map_target(target: dict, out: Path, workspace: Path | None = None) -> dict:
    root = Path(target["root"])
    skip = set(SKIP_DIR_NAMES)
    util.say("code", f"{target['label']}: listing the code files, and telling C++ headers from C headers")
    lists = list_sources_by(root, {**{lang: reader.EXTENSIONS for lang, reader in READERS},
                                   "C++": cpp_lang.EXTENSIONS, "VHDL": vhdl_lang.EXTENSIONS}, skip)
    found = {lang: lists[lang] for lang, _ in READERS}
    found["C++"] = lists["C++"]
    vhdl_files = lists["VHDL"]
    if workspace is not None:
        ws = str(workspace.resolve()).lower()
        for lang in found:
            found[lang] = [f for f in found[lang] if not str(Path(f[0]).resolve()).lower().startswith(ws)]
    # A .h file belongs to C++ when its own text is C++ (classes, namespaces, templates, ::), else to C.
    headers = [f for f in found["C"] if f[1].lower().endswith(".h")]
    told = parallel.map_in_order(_header_is_cpp, [full for full, _ in headers])
    cpp_headers = [f for f, is_cpp in zip(headers, told, strict=True) if is_cpp]
    if cpp_headers:
        moved = set(cpp_headers)
        found["C"] = [f for f in found["C"] if f not in moved]
        found["C++"] = sorted(found["C++"] + cpp_headers, key=lambda pair: pair[1])
    cpp_files = found.pop("C++")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rels = [rel for files in found.values() for _, rel in files] + [rel for _, rel in cpp_files]
    depth = int(target.get("module_depth") or module_depth(rels)) if rels else 1
    util.live("codefiles", target=target["name"], files=len(rels) + len(vhdl_files))
    counts = [(lang, len(found[lang])) for lang, _ in READERS] + [("C++", len(cpp_files)), ("VHDL", len(vhdl_files))]
    util.say("code", f"{target['label']}: {util.count(len(rels) + len(vhdl_files), 'code file')} ("
                     + (", ".join(f"{lang} {n:,}" for lang, n in counts if n) or "none") + ")")
    defs, file_info, extras = [], {}, {"prototypes": {}, "macro_map": {}, "module_includes": {}}
    for lang, reader in READERS:
        if not found[lang]:
            continue
        with util.progress("code", f"reading {lang}", len(found[lang])):
            d, fi, ex = reader.analyze(str(root), found[lang], depth)
        util.say("code", f"  {lang}: {util.count(len(found[lang]), 'file')} read, {util.count(len(d), 'function')}")
        defs.extend(d)
        file_info.update(fi)
        for k in extras:
            extras[k].update(ex.get(k, {}))
        util.live("coderead", target=target["name"], files=len(found[lang]), language=lang)
    if cpp_files:
        # C++ may call the C functions of the same code base, and C may call C++ functions with C linkage.
        c_defs = [d for d in defs if d["lang"] == "C"]
        with util.progress("code", "reading C++", len(cpp_files)):
            d, fi, ex = cpp_lang.analyze(str(root), cpp_files, depth, c_defs)
        cpp_lang.link_c_callers(c_defs, d, ex["c_linkage"])
        util.say("code", f"  C++: {util.count(len(cpp_files), 'file')} read, {util.count(len(d), 'function')} and methods")
        defs.extend(d)
        file_info.update(fi)
        extras["prototypes"].update(ex["prototypes"])
        extras["macro_map"].update(ex["macro_map"])
        extras["module_includes"] = _module_includes(file_info)
        extras["cpp"] = ex["cpp"]
        util.live("coderead", target=target["name"], files=len(cpp_files), language="C++")
    extras["module_depth"] = depth
    util.say("code", "  writing the code map: functions, calls, modules, the name lookup")
    summary = write_map(out, target, defs, file_info, extras)
    if vhdl_files:
        with util.progress("code", "reading VHDL", len(vhdl_files)):
            summary["vhdl"] = vhdl_lang.map_vhdl(str(root), vhdl_files, out, target)
        util.live("coderead", target=target["name"], files=len(vhdl_files), language="VHDL")
    with util.progress("code", "named numbers in the code: constants, parameters, generics", len(rels) + len(vhdl_files)):
        summary["values_count"] = values.write(out, {**found, "C++": cpp_files, "VHDL": vhdl_files}, file_info, defs)
    util.say("code", f"  {util.count(summary['values_count'], 'named number')} in the code (values.jsonl)")
    util.save_json(out / "overview.json", summary)
    return summary


def build(proj: Project) -> dict:
    """Write code/<target>/ for every code base, and code/codebases.json."""
    proj.code_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for t in proj.code_targets:
        if not Path(t["root"]).is_dir():
            util.say("code", f"{t['label']}: folder not found at {t['root']}")
            continue
        s = map_target(t, proj.code_dir / t["name"], proj.workspace)
        results[t["name"]] = s
        vh = s.get("vhdl")
        extra = f", VHDL {vh['entities_count']} entities" if vh else ""
        util.say("code", f"{t['label']}: {s['functions_count']} functions, {s['call_edges_count']} calls, "
                         f"{s['modules_count']} modules{extra}")
    # drop maps of code bases that are no longer in the project
    keep = set(results)
    for child in sorted(proj.code_dir.iterdir()):
        if child.is_dir() and child.name not in keep:
            shutil.rmtree(child)
    util.save_json(proj.code_dir / "codebases.json", [
        {"name": t["name"], "label": t["label"], "folder": t["folder"]} for t in proj.code_targets
        if t["name"] in results])
    return results
