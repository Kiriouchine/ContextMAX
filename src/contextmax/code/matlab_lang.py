"""MATLAB and Octave: functions, local functions and scripts, and the calls between them.

`x(3)` and `f(3)` are the same syntax in MATLAB: one indexes, the other calls. The only
deterministic way to tell them apart is the scope itself, so a name the scope assigns to
(or receives as an argument, or declares global) is a variable and never becomes a call.
A call resolves to a local function in the same file first, then to a function file of that
name in these folders, which is how MATLAB's own path lookup behaves.
"""
from __future__ import annotations

import re
from collections import defaultdict

from contextmax import util
from contextmax.code.common import first_sentence, module_for, role_for

EXTENSIONS = {".m"}

M_FUNC = re.compile(
    r"^\s*function\s+(?:\[(?P<outs>[^\]]*)\]\s*=\s*|(?P<out>[A-Za-z]\w*)\s*=\s*)?"
    r"(?P<name>[A-Za-z]\w*(?:\.[A-Za-z]\w*)?)\s*(?:\((?P<args>[^)]*)\))?\s*$")
M_CALL = re.compile(r"(?<![\w.])([A-Za-z]\w{0,62})\s*\(")
M_BARE = re.compile(r"(?<![\w.'\"])([A-Za-z]\w{0,62})\s*(?:;|,|$)")
M_KEYWORDS = {
    "if", "elseif", "else", "end", "for", "while", "switch", "case", "otherwise", "function", "return",
    "break", "continue", "try", "catch", "global", "persistent", "parfor", "spmd", "classdef", "properties",
    "methods", "events", "enumeration", "arguments", "and", "or", "not", "true", "false", "pi", "eps", "inf",
    "Inf", "nan", "NaN", "i", "j", "ans", "clc", "clear", "close", "all", "on", "off", "hold", "grid",
}
M_ASSIGN = re.compile(r"(?:^|[;,])\s*([A-Za-z]\w*)\s*(?:\([^)]*\)|\{[^}]*\}|\.[\w.]+)?\s*=(?!=)")
M_MULTI = re.compile(r"^\s*\[([^\]]*)\]\s*=(?!=)")
M_FOR = re.compile(r"^\s*(?:par)?for\s+\(?\s*([A-Za-z]\w*)\s*=")
M_DECL = re.compile(r"^\s*(?:global|persistent)\s+(.+)$")
M_NAME = re.compile(r"[A-Za-z]\w*")


def strip_matlab(text: str) -> list[str]:
    """Blank comments and strings line by line. A quote after a name, a number or a closing
    bracket is the transpose operator; anywhere else it opens a string."""
    out: list[str] = []
    in_block = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped == "%{":
            in_block = True
        if in_block:
            out.append("")
            if stripped == "%}":
                in_block = False
            continue
        cleaned: list[str] = []
        quote = None
        for ch in line:
            if quote is not None:
                cleaned.append(" ")
                if ch == quote:
                    quote = None
                continue
            if ch == "%":
                break
            if ch == '"' or (ch == "'" and not _transposes(cleaned)):
                quote = ch
                cleaned.append(" ")
                continue
            cleaned.append(ch)
        out.append("".join(cleaned).rstrip("\r"))
    return out


def _transposes(cleaned: list[str]) -> bool:
    previous = "".join(cleaned).rstrip()
    return bool(previous) and (previous[-1].isalnum() or previous[-1] in "_)]}.'")


def assigned_names(lines: list[str]) -> set[str]:
    names: set[str] = set()
    for line in lines:
        m = M_MULTI.match(line)
        if m:
            names.update(M_NAME.findall(m.group(1)))
        for m in M_ASSIGN.finditer(line):
            names.add(m.group(1))
        m = M_FOR.match(line)
        if m:
            names.add(m.group(1))
        m = M_DECL.match(line)
        if m:
            names.update(M_NAME.findall(m.group(1)))
    return names


def help_line(raw_lines: list[str], start: int) -> str:
    """MATLAB's own one-line description: the first comment after the declaration (H1)."""
    for line in raw_lines[start:start + 3]:
        s = line.strip()
        if s.startswith("%"):
            return first_sentence(s.lstrip("%").strip())
        if s:
            break
    return ""


def _calls(lines: list[str], local: set[str]) -> list[str]:
    body = "\n".join(lines)
    found: dict[str, None] = {}
    for rx in (M_CALL, M_BARE):
        for m in rx.finditer(body):
            name = m.group(1)
            if name in M_KEYWORDS or name in local:
                continue
            found.setdefault(name)
    return list(found)


def analyze(root: str, files: list[tuple[str, str]], depth: int):
    defs: list[dict] = []
    file_info: dict[str, dict] = {}
    primary: dict[str, list[str]] = defaultdict(list)     # function-file name -> keys
    pending: list[tuple[int, list[str], dict[str, str]]] = []
    for full, rel in files:
        text = util.load_text(full)
        raw = text.split("\n")
        code = strip_matlab(text)
        stem = rel.rsplit("/", 1)[-1][:-2]
        mod = module_for(rel, depth)
        role = role_for(rel)
        starts = [(i + 1, m) for i, line in enumerate(code) if (m := M_FUNC.match(line))]
        is_classdef = any(line.strip().startswith("classdef") for line in code[:50])
        local_keys: dict[str, str] = {}
        rows = []
        if not starts:
            local = assigned_names(code)
            rows.append(({
                "key": f"{rel}#{stem}", "name": stem, "qualname": stem, "lang": "MATLAB", "kind": "script",
                "module": mod, "role": role, "file": rel, "ret": "", "params": [], "first_line": 1,
                "last_line": len(raw), "lines_count": len(raw), "file_local": False, "doc": help_line(raw, 0),
                "variables": sorted(local)[:200], "variables_count": len(local),
                "call_keys": [], "via_macros": [], "external_calls": [], "ambiguous": [], "indirect_calls": [],
            }, _calls(code, local | {stem})))
            primary[stem].append(f"{rel}#{stem}")
        for n, (line_no, m) in enumerate(starts):
            end = starts[n + 1][0] - 1 if n + 1 < len(starts) else len(raw)
            while end > line_no and not raw[end - 1].strip():
                end -= 1
            name = m.group("name")
            args = [a.strip() for a in (m.group("args") or "").split(",") if a.strip()]
            outs = [o.strip() for o in (m.group("outs") or m.group("out") or "").split(",") if o.strip()]
            scope = code[line_no:end]
            local = assigned_names(scope) | set(args) | set(outs)
            kind = "method" if is_classdef else ("function" if n == 0 else "local function")
            key = f"{rel}#{name}"
            if any(r[0]["key"] == key for r in rows):
                key = f"{rel}#{name}~{line_no}"
            rows.append(({
                "key": key, "name": name, "qualname": name, "lang": "MATLAB", "kind": kind,
                "module": mod, "role": role, "file": rel, "ret": ", ".join(outs), "params": args,
                "first_line": line_no, "last_line": end, "lines_count": end - line_no + 1,
                "file_local": n > 0 and not is_classdef, "doc": help_line(raw, line_no),
                "variables": sorted(local - set(args) - set(outs))[:200],
                "variables_count": len(local - set(args) - set(outs)),
                "call_keys": [], "via_macros": [], "external_calls": [], "ambiguous": [], "indirect_calls": [],
            }, _calls(scope, local | {name})))
            local_keys.setdefault(name, key)
            if n == 0 and name == stem:
                primary[stem].append(key)
        for rec, calls in rows:
            pending.append((len(defs), calls, local_keys))
            defs.append(rec)
        file_info[rel] = {"module": mod, "role": role, "lang": "MATLAB", "ext": ".m", "lines_count": len(raw),
                          "includes": [], "defs_count": len(rows)}

    for idx, calls, local_keys in pending:
        d = defs[idx]
        for name in calls:
            if name in local_keys and local_keys[name] != d["key"]:
                d["call_keys"].append(local_keys[name])
            elif name in primary:
                cands = primary[name]
                if len(cands) == 1:
                    d["call_keys"].append(cands[0])
                else:
                    same = [c for c in cands if c.startswith(d["file"].rsplit("/", 1)[0] + "/")]
                    chosen = same[0] if same else cands[0]
                    d["call_keys"].append(chosen)
                    d["ambiguous"].append([name, cands])
            elif name not in local_keys:
                d["external_calls"].append(name)
    return defs, file_info, {}
