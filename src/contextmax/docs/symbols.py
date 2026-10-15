"""Which code names a document can be said to mention: precision first.

A document is tied to code only through names that cannot be ordinary words: function names
with an underscore or an inner capital, constants in capitals with an underscore, and the
VHDL entities of the design. "update" or "init" in prose proves nothing; "pid_step" or
"MOTOR_MAX_SPEED" does. An ordinary word never draws a line; a single distinctive name draws the
weakest kind (confidence "one", shown dashed).
"""
from __future__ import annotations

import ast
import os
import re
from collections import defaultdict
from pathlib import Path

from contextmax import util
from contextmax.code import cpp_lang

_DEFINE_NAME = re.compile(r"^ \s* \# \s* define \s+ ([_A-Za-z]\w*)", re.MULTILINE | re.VERBOSE)
_INNER_CAPITAL = re.compile(r"[a-z][A-Z]")
# Capitals that are words, not names of this project.
_PLAIN_CONSTANTS = frozenset("DEBUG ERROR FALSE GET MAX MIN NO NONE NULL OFF OK ON SET TRUE YES".split())
# Function names too common to point at one piece of code.
_PLAIN_NAMES = frozenset("""
    close execute get handle helper init load main open print process read reset run save set setup start stop
    test update write
""".split())
_GUARD_ENDINGS = ("_INCLUDED", "_HPP", "_H_", "_H")          # include guards, not constants


def reads_as_code(name: str) -> bool:
    """A name that reads as code, not as a word of prose."""
    if len(name) < 5 or name.startswith("__") or name.lower() in _PLAIN_NAMES:
        return False
    pieces = [p for p in name.split("_") if p]
    if len(pieces) >= 2 and sum(len(p) >= 2 for p in pieces) >= 2:
        return True
    return len(name) >= 6 and bool(_INNER_CAPITAL.search(name))


def entity_reads_as_code(name: str) -> bool:
    return len(name) >= 5 and "_" in name


def _constant_name(name: str) -> bool:
    return len(name) >= 5 and "_" in name and name == name.upper() and name not in _PLAIN_CONSTANTS


def _c_constants(path: Path, module: str, target: str, into: dict) -> None:
    try:
        text = util.load_text(path)
    except OSError:
        return
    for m in _DEFINE_NAME.finditer(text):
        name = m.group(1)
        if _constant_name(name) and not name.endswith(_GUARD_ENDINGS):
            into[name].add((target, module, "constant"))


def _cpp_constants(path: Path, module: str, target: str, into: dict) -> None:
    try:
        text = util.load_text(path)
    except OSError:
        return
    for name in cpp_lang.constants(text):
        if _constant_name(name) and not name.endswith(_GUARD_ENDINGS):
            into[name].add((target, module, "constant"))


def _python_constants(path: Path, module: str, target: str, into: dict) -> None:
    try:
        tree = ast.parse(util.load_text(path))
    except (SyntaxError, ValueError, OSError):
        return
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = node.targets
        elif isinstance(node, ast.AnnAssign):
            names = [node.target]
        else:
            continue
        for item in names:
            if isinstance(item, ast.Name) and _constant_name(item.id):
                into[item.id].add((target, module, "constant"))


def collect_names(code_dir: Path, targets: list[dict]) -> tuple[dict, dict]:
    """(exact, folded): case-sensitive names to definitions, and case-folded VHDL entities."""
    exact: dict[str, set] = defaultdict(set)
    folded: dict[str, set] = defaultdict(set)
    for t in targets:
        base, name = code_dir / t["name"], t["name"]
        for symbol, definitions in (util.load_json(base / "name-lookup.json", default={}) or {}).items():
            places = {(name, d["module"], "function") for d in definitions if d.get("module")}
            if places and reads_as_code(symbol):
                exact[symbol] |= places
            for d in definitions:
                # a C++ name written with its class or namespace (`Controller::clamp`) always reads as code
                pieces = (d.get("qualname") or "").split("::")
                for k in range(len(pieces) - 1):
                    if d.get("module"):
                        exact["::".join(pieces[k:])].add((name, d["module"], "function"))
        root = Path(t["root"])
        readers = {".h": _c_constants, ".hpp": _c_constants, ".py": _python_constants}
        for rel, info in (util.load_json(base / "file-list.json", default={}) or {}).items():
            reader = _cpp_constants if info.get("lang") == "C++" else readers.get(os.path.splitext(rel)[1].lower())
            if reader:
                reader(root / rel, info["module"], name, exact)
        for entity in util.load_jsonl(base / "hdl-entities.jsonl"):
            label = entity.get("name") or ""
            if entity.get("in_hdl_design") and entity_reads_as_code(label):
                folded[label.lower()].add((label, name, t.get("label", name), "entity"))
    return dict(exact), dict(folded)
