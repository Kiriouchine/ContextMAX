"""Python: functions, methods and classes, read with Python's own parser.

A call becomes an edge only when the text proves where it goes: a function defined in the
same file, a name imported from a file in these folders, a module imported from these
folders (`util.save()`), or a method of the same class (`self.save()`). A call on any other
object depends on what that object is at run time, so it is listed as not followed.
"""
from __future__ import annotations

import ast

from contextmax import util
from contextmax.code.common import first_sentence, module_for, role_for

EXTENSIONS = {".py", ".pyw"}


def _dotted_names(rel: str) -> list[str]:
    """Every dotted name a file could be imported as: a.b.c, b.c and c for a/b/c.py."""
    parts = rel[:-3].split("/") if rel.endswith(".py") else rel.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[i:]) for i in range(len(parts)) if parts[i:]]


class _Defs(ast.NodeVisitor):
    def __init__(self, rel: str, module: str, role: str, raw_lines: list[str]):
        self.rel, self.module, self.role = rel, module, role
        self.raw = raw_lines
        self.stack: list[str] = []
        self.class_stack: list[str] = []
        self.rows: list[dict] = []
        self.calls: list[tuple[int, ast.AST, str | None]] = []   # (row index, call node, enclosing class)
        self.seen_keys: set[str] = set()

    def _add(self, node, kind: str, name: str, params: list[str], ret: str) -> int:
        qual = ".".join(self.stack + [name])
        key = f"{self.rel}#{qual}"
        n = 2
        while key in self.seen_keys:
            key = f"{self.rel}#{qual}~{n}"
            n += 1
        self.seen_keys.add(key)
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        start = node.lineno
        decos = getattr(node, "decorator_list", [])
        if decos:
            start = min(start, min(d.lineno for d in decos))
        self.rows.append({
            "key": key, "name": name, "qualname": qual, "lang": "Python", "kind": kind,
            "module": self.module, "role": self.role, "file": self.rel, "ret": ret, "params": params,
            "first_line": start, "last_line": end, "lines_count": end - start + 1,
            "file_local": name.startswith("_") and not name.startswith("__"),
            "doc": first_sentence(ast.get_docstring(node) or ""),
            "call_keys": [], "via_macros": [], "external_calls": [], "ambiguous": [], "indirect_calls": [],
            "_class": self.class_stack[-1] if self.class_stack else None,
        })
        return len(self.rows) - 1

    def visit_ClassDef(self, node):
        idx = self._add(node, "class", node.name, [ast.unparse(b) for b in node.bases], "")
        self.stack.append(node.name)
        self.class_stack.append(".".join(self.stack))
        for child in node.body:
            self.visit(child)
        self.class_stack.pop()
        self.stack.pop()
        self._scan_calls(idx, [b for b in node.body if not isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], None)

    def _function(self, node):
        args = node.args
        params = [a.arg for a in args.posonlyargs + args.args]
        if args.vararg:
            params.append("*" + args.vararg.arg)
        params += [a.arg for a in args.kwonlyargs]
        if args.kwarg:
            params.append("**" + args.kwarg.arg)
        ret = ast.unparse(node.returns) if node.returns else ""
        kind = "method" if self.class_stack and self.stack and ".".join(self.stack) == self.class_stack[-1] else "function"
        idx = self._add(node, kind, node.name, params, ret)
        enclosing_class = self.class_stack[-1] if kind == "method" else None
        self.stack.append(node.name)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(child)
        self.stack.pop()
        self._scan_calls(idx, [c for c in node.body if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))],
                         enclosing_class)

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def _scan_calls(self, idx: int, nodes: list, enclosing_class: str | None):
        for stmt in nodes:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Call):
                    self.calls.append((idx, sub, enclosing_class))


def analyze(root: str, files: list[tuple[str, str]], depth: int):
    defs: list[dict] = []
    file_info: dict[str, dict] = {}
    by_file_top: dict[str, dict[str, str]] = {}        # rel -> top-level name -> key
    by_qual: dict[str, str] = {}                        # rel#qualname -> key
    module_file: dict[str, str] = {}                    # dotted name -> rel
    parsed = []
    for _full, rel in files:
        for dn in _dotted_names(rel):
            module_file.setdefault(dn, rel)
    for full, rel in files:
        util.tick(rel)
        text = util.load_text(full)
        mod = module_for(rel, depth)
        role = role_for(rel)
        try:
            tree = ast.parse(text, filename=rel)
        except (SyntaxError, ValueError) as exc:
            file_info[rel] = {"module": mod, "role": role, "lang": "Python", "ext": ".py",
                              "lines_count": text.count("\n") + 1, "includes": [], "defs_count": 0,
                              "error": f"cannot parse: {exc.__class__.__name__} line {getattr(exc, 'lineno', '?')}"}
            continue
        v = _Defs(rel, mod, role, text.split("\n"))
        for node in tree.body:
            v.visit(node)
        top_level = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        if any(isinstance(sub, ast.Call) for n in top_level for sub in ast.walk(n)):
            # code that runs on import or as a script gets a record of its own, so its calls count
            module_calls_idx = len(v.rows)
            v.rows.append({
                "key": f"{rel}#<module>", "name": f"<{rel.rsplit('/', 1)[-1]}>", "qualname": "<module>",
                "lang": "Python", "kind": "module", "module": mod, "role": role, "file": rel, "ret": "",
                "params": [], "first_line": 1, "last_line": text.count("\n") + 1,
                "lines_count": text.count("\n") + 1, "file_local": False,
                "doc": first_sentence(ast.get_docstring(tree) or ""),
                "call_keys": [], "via_macros": [], "external_calls": [], "ambiguous": [], "indirect_calls": [],
                "_class": None})
            v._scan_calls(module_calls_idx, top_level, None)
        imports = _imports(tree, rel, module_file)
        offset = len(defs)
        for r in v.rows:
            defs.append(r)
            by_qual[f"{rel}#{r['qualname']}"] = r["key"]
        by_file_top[rel] = {r["name"]: r["key"] for r in v.rows if "." not in r["qualname"] and r["kind"] != "module"}
        parsed.append((rel, v, imports, offset))
        file_info[rel] = {"module": mod, "role": role, "lang": "Python", "ext": ".py",
                          "lines_count": text.count("\n") + 1,
                          "includes": sorted({m for m in imports["modules"].values()} |
                                             {f for f, _ in imports["names"].values()}),
                          "defs_count": len(v.rows)}

    # A method name defined somewhere in these folders could be the target of a call on an
    # object of unknown type; any other method name belongs to a library type.
    project_names = {d["name"] for d in defs if d["kind"] in ("function", "method")}
    for rel, v, imports, offset in parsed:
        for idx, call, enclosing in v.calls:
            d = defs[offset + idx]
            func = call.func
            target = None
            if isinstance(func, ast.Name):
                target = by_file_top.get(rel, {}).get(func.id)
                if target is None and func.id in imports["names"]:
                    frel, fname = imports["names"][func.id]
                    target = by_file_top.get(frel, {}).get(fname)
                if target is None:
                    if func.id not in d["external_calls"]:
                        d["external_calls"].append(func.id)
            elif isinstance(func, ast.Attribute):
                base = func.value
                name = None
                if isinstance(base, ast.Name) and base.id in ("self", "cls") and enclosing:
                    target = by_qual.get(f"{rel}#{enclosing}.{func.attr}")
                    if target is None:
                        name = f".{func.attr}"
                elif isinstance(base, ast.Name) and base.id in imports["modules"]:
                    target = by_file_top.get(imports["modules"][base.id], {}).get(func.attr)
                    if target is None:
                        name = f"{base.id}.{func.attr}"
                elif isinstance(base, ast.Name) and base.id in imports["external"]:
                    name = f"{base.id}.{func.attr}"
                else:
                    name = f".{func.attr}"
                if target is None and func.attr in project_names:
                    d["indirect_calls"].append({"expr": _short(func), "line": call.lineno})
                elif target is None and name and name not in d["external_calls"]:
                    d["external_calls"].append(name)
            if target and target != d["key"] and target not in d["call_keys"]:
                d["call_keys"].append(target)
        for d in defs[offset:offset + len(v.rows)]:
            d["indirect_calls"] = sorted({(c["line"], c["expr"]) for c in d["indirect_calls"]})
            d["indirect_calls"] = [{"expr": e, "line": ln} for ln, e in d["indirect_calls"]]
            d.pop("_class", None)
    return defs, file_info, {}


def _short(node: ast.AST) -> str:
    try:
        text = ast.unparse(node)
    except Exception:  # noqa: BLE001 - unparse of odd nodes is cosmetic only
        return "?"
    return text if len(text) <= 60 else text[:57] + "..."


def _imports(tree: ast.Module, rel: str, module_file: dict[str, str]) -> dict:
    """Names and modules this file imports from files in the same code base."""
    names: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    external: set[str] = set()
    package = rel.rsplit("/", 1)[0].replace("/", ".") if "/" in rel else ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                frel = module_file.get(a.name)
                if frel:
                    modules[a.asname or a.name] = frel
                else:
                    external.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                parts = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                base = ".".join([p for p in parts if p] + ([node.module] if node.module else []))
            for a in node.names:
                local = a.asname or a.name
                sub = module_file.get(f"{base}.{a.name}" if base else a.name)
                if sub:
                    modules[local] = sub          # from pkg import module
                    continue
                frel = module_file.get(base)
                if frel:
                    names[local] = (frel, a.name)  # from module import function
                elif not node.level:
                    external.add(local)
    return {"names": names, "modules": modules, "external": external}
