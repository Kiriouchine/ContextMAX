"""Map every code base of a project: C, C++, Python and MATLAB into one call graph, VHDL into its hierarchy."""
from __future__ import annotations

import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from contextmax import util
from contextmax.catalogue import SKIP_DIR_NAMES
from contextmax.code import c_lang, cpp_lang, matlab_lang, python_lang, vhdl_lang
from contextmax.code.common import list_sources, module_depth, write_map
from contextmax.project import Project

READERS = [("C", c_lang), ("Python", python_lang), ("MATLAB", matlab_lang)]


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
    found = {}
    for lang, reader in READERS:
        found[lang] = list_sources(root, reader.EXTENSIONS, skip)
    found["C++"] = list_sources(root, cpp_lang.EXTENSIONS, skip)
    vhdl_files = list_sources(root, vhdl_lang.EXTENSIONS, skip)
    if workspace is not None:
        ws = str(workspace.resolve()).lower()
        for lang in found:
            found[lang] = [f for f in found[lang] if not str(Path(f[0]).resolve()).lower().startswith(ws)]
    # A .h file belongs to C++ when its own text is C++ (classes, namespaces, templates, ::), else to C.
    cpp_headers = [f for f in found["C"] if f[1].lower().endswith(".h") and cpp_lang.is_cpp_header(util.load_text(f[0]))]
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
    defs, file_info, extras = [], {}, {"prototypes": {}, "macro_map": {}, "module_includes": {}}
    for lang, reader in READERS:
        if not found[lang]:
            continue
        d, fi, ex = reader.analyze(str(root), found[lang], depth)
        defs.extend(d)
        file_info.update(fi)
        for k in extras:
            extras[k].update(ex.get(k, {}))
        util.live("coderead", target=target["name"], files=len(found[lang]), language=lang)
    if cpp_files:
        # C++ may call the C functions of the same code base, and C may call C++ functions with C linkage.
        c_defs = [d for d in defs if d["lang"] == "C"]
        d, fi, ex = cpp_lang.analyze(str(root), cpp_files, depth, c_defs)
        cpp_lang.link_c_callers(c_defs, d, ex["c_linkage"])
        defs.extend(d)
        file_info.update(fi)
        extras["prototypes"].update(ex["prototypes"])
        extras["macro_map"].update(ex["macro_map"])
        extras["module_includes"] = _module_includes(file_info)
        extras["cpp"] = ex["cpp"]
        util.live("coderead", target=target["name"], files=len(cpp_files), language="C++")
    extras["module_depth"] = depth
    summary = write_map(out, target, defs, file_info, extras)
    if vhdl_files:
        summary["vhdl"] = vhdl_lang.map_vhdl(str(root), vhdl_files, out, target)
        util.save_json(out / "overview.json", summary)
        util.live("coderead", target=target["name"], files=len(vhdl_files), language="VHDL")
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
