"""Map every code base of a project: C, Python and MATLAB into one call graph, VHDL into its hierarchy."""
from __future__ import annotations

import shutil
from pathlib import Path

from contextmax import util
from contextmax.catalogue import SKIP_DIR_NAMES
from contextmax.code import c_lang, matlab_lang, python_lang, vhdl_lang
from contextmax.code.common import list_sources, module_depth, write_map
from contextmax.project import Project

READERS = [("C", c_lang), ("Python", python_lang), ("MATLAB", matlab_lang)]


def map_target(target: dict, out: Path, workspace: Path | None = None) -> dict:
    root = Path(target["root"])
    skip = set(SKIP_DIR_NAMES)
    found = {}
    for lang, reader in READERS:
        found[lang] = list_sources(root, reader.EXTENSIONS, skip)
    vhdl_files = list_sources(root, vhdl_lang.EXTENSIONS, skip)
    if workspace is not None:
        ws = str(workspace.resolve()).lower()
        for lang in found:
            found[lang] = [f for f in found[lang] if not str(Path(f[0]).resolve()).lower().startswith(ws)]
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rels = [rel for files in found.values() for _, rel in files]
    depth = int(target.get("module_depth") or module_depth(rels)) if rels else 1
    defs, file_info, extras = [], {}, {"prototypes": {}, "macro_map": {}, "module_includes": {}}
    for lang, reader in READERS:
        if not found[lang]:
            continue
        d, fi, ex = reader.analyze(str(root), found[lang], depth)
        defs.extend(d)
        file_info.update(fi)
        for k in extras:
            extras[k].update(ex.get(k, {}))
    extras["module_depth"] = depth
    summary = write_map(out, target, defs, file_info, extras)
    if vhdl_files:
        summary["vhdl"] = vhdl_lang.map_vhdl(str(root), vhdl_files, out, target)
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
