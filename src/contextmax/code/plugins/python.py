# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Tier A plugin for Python (`python-ast-v1`), built on the standard library `ast`.

Exact spans from `end_lineno`, every definition including nested ones, module-level and
class-body calls attributed correctly, imports with relative levels and aliases, and a
resolution hint on each call site so `resolve.py` can follow imports and `self`.
"""

from __future__ import annotations

import ast
import hashlib
import re

from contextmax.code import lexical
from contextmax.code.base import CallSite, FileAnalysis, Import, Symbol

PLUGIN_ID = "python-ast-v1"
PLUGIN_VERSION = "1"
LANGUAGE = "python"
MAX_VALUE_PREVIEW = 80
_UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _dotted(node: ast.AST) -> str | None:
    """Render `a.b.c` from Name/Attribute chains; None for anything else (calls, subscripts)."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive, unparse handles every node ast produces
        return None


def _params(args: ast.arguments) -> list[dict]:
    out: list[dict] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for arg, default in zip(positional, defaults, strict=True):
        entry: dict = {"name": arg.arg}
        if arg.annotation is not None:
            entry["type"] = _unparse(arg.annotation)
        if default is not None:
            entry["default"] = (_unparse(default) or "")[:MAX_VALUE_PREVIEW]
        out.append(entry)
    if args.vararg is not None:
        entry = {"name": "*" + args.vararg.arg}
        if args.vararg.annotation is not None:
            entry["type"] = _unparse(args.vararg.annotation)
        out.append(entry)
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        entry = {"name": arg.arg}
        if arg.annotation is not None:
            entry["type"] = _unparse(arg.annotation)
        if default is not None:
            entry["default"] = (_unparse(default) or "")[:MAX_VALUE_PREVIEW]
        out.append(entry)
    if args.kwarg is not None:
        entry = {"name": "**" + args.kwarg.arg}
        if args.kwarg.annotation is not None:
            entry["type"] = _unparse(args.kwarg.annotation)
        out.append(entry)
    return out


def _doc(node: ast.AST) -> str | None:
    try:
        text = ast.get_docstring(node, clean=True)
    except TypeError:
        return None
    if not text:
        return None
    paragraph = text.strip().split("\n\n", 1)[0]
    return " ".join(paragraph.split())[: lexical.MAX_DOC_CHARS]


class _Collector(ast.NodeVisitor):
    def __init__(self, key: str, lines: list[str]) -> None:
        self.key = key
        self.lines = lines
        self.symbols: list[Symbol] = []
        self.calls: list[CallSite] = []
        self.imports: list[Import] = []
        self.alias_map: dict[str, tuple[str, str]] = {}  # local name -> (module, name)
        self.scope: list[tuple[str, str]] = []  # (qualname, kind)
        self.class_stack: list[str] = []

    # -- helpers ---------------------------------------------------------------------------
    def _qual(self, name: str) -> str:
        return f"{self.scope[-1][0]}.{name}" if self.scope else name

    def _caller(self) -> str | None:
        return self.scope[-1][0] if self.scope else None

    def _content_hash(self, node: ast.AST) -> str:
        start, end = node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno
        body = "\n".join(line.rstrip() for line in self.lines[start - 1 : end])
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _add_symbol(self, node: ast.AST, name: str, kind: str, signature: str, **extra) -> Symbol:
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        first_line = node.lineno
        decorators = [f"@{_unparse(d)}" for d in getattr(node, "decorator_list", [])]
        if decorators:
            first_line = min(d.lineno for d in node.decorator_list)
        sym = Symbol(
            name=name,
            qualname=self._qual(name),
            kind=kind,
            line=node.lineno,
            end_line=end,
            end_exact=True,
            signature=signature[:300],
            doc=extra.pop("doc", None),
            parent=self.scope[-1][0] if self.scope else None,
            visibility="private" if name.startswith("_") else "public",
            decorators=decorators,
            content_hash=self._content_hash(node),
            **extra,
        )
        sym.extra["decorated_from"] = first_line
        self.symbols.append(sym)
        return sym

    # -- definitions -----------------------------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node, "async-function")

    def _function(self, node, kind: str) -> None:
        in_class = bool(self.scope) and self.scope[-1][1] == "class"
        sym_kind = "method" if in_class else kind
        if in_class and node.name == "__init__":
            sym_kind = "constructor"
        params = _params(node.args)
        returns = _unparse(node.returns) if node.returns is not None else None
        sig = f"def {node.name}({', '.join(p['name'] + (': ' + p['type'] if 'type' in p else '') for p in params)})"
        if returns:
            sig += f" -> {returns}"
        self._add_symbol(
            node, node.name, sym_kind, sig, params=params, returns=returns, doc=_doc(node)
        )
        self.scope.append((self._qual(node.name), "function"))
        for dec in node.decorator_list:
            self.visit(dec)
        for default in list(node.args.defaults) + [
            d for d in node.args.kw_defaults if d is not None
        ]:
            self.visit(default)
        for stmt in node.body:
            self.visit(stmt)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [_unparse(b) or "" for b in node.bases]
        sig = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
        self._add_symbol(
            node, node.name, "class", sig, doc=_doc(node), params=[{"name": b} for b in bases]
        )
        self.scope.append((self._qual(node.name), "class"))
        self.class_stack.append(self.scope[-1][0])
        # Base classes are recorded as references owned by the class itself (inheritance).
        for base in node.bases:
            dotted = _dotted(base)
            if dotted:
                name, qualifier = (
                    dotted.rsplit(".", 1)[-1],
                    dotted.rsplit(".", 1)[0] if "." in dotted else None,
                )
                self.calls.append(
                    CallSite(
                        caller=self._caller(),
                        name=name,
                        qualifier=qualifier,
                        line=base.lineno,
                        col=base.col_offset + 1,
                        kind="reference",
                        hint=self._hint(dotted),
                    )
                )
        for dec in node.decorator_list:
            self.visit(dec)
        for stmt in node.body:
            self.visit(stmt)
        self.class_stack.pop()
        self.scope.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        self._assignment(node, node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._assignment(node, [node.target], node.value, annotation=node.annotation)
        self.generic_visit(node)

    def _assignment(self, node, targets, value, annotation=None) -> None:
        depth_kind = self.scope[-1][1] if self.scope else "module"
        if depth_kind == "function":
            return  # locals are not catalogued
        for target in targets:
            names = []
            if isinstance(target, ast.Name):
                names = [target.id]
            elif isinstance(target, ast.Tuple):
                names = [e.id for e in target.elts if isinstance(e, ast.Name)]
            for name in names:
                kind = (
                    "constant"
                    if _UPPER.match(name)
                    else ("field" if depth_kind == "class" else "variable")
                )
                preview = (_unparse(value) or "")[:MAX_VALUE_PREVIEW] if value is not None else ""
                sig = (
                    f"{name}"
                    + (f": {_unparse(annotation)}" if annotation is not None else "")
                    + (f" = {preview}" if preview else "")
                )
                self._add_symbol(
                    node,
                    name,
                    kind,
                    sig,
                    returns=_unparse(annotation) if annotation is not None else None,
                )

    # -- imports ---------------------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.alias_map[local] = (alias.name, "")
            self.imports.append(
                Import(
                    module=alias.name,
                    line=node.lineno,
                    kind="import",
                    names=[],
                    alias=alias.asname,
                    relative=False,
                    raw=f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""),
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        names = [a.name for a in node.names]
        for alias in node.names:
            local = alias.asname or alias.name
            self.alias_map[local] = (module, alias.name)
        aliases = [a.asname for a in node.names if a.asname]
        self.imports.append(
            Import(
                module=module,
                line=node.lineno,
                kind="import",
                names=names,
                alias=aliases[0] if len(aliases) == 1 else None,
                relative=node.level > 0,
                raw=f"from {module} import {', '.join(names)}"[:200],
            )
        )

    # -- calls -----------------------------------------------------------------------------
    def _hint(self, dotted: str) -> tuple[str, str] | None:
        head, _, rest = dotted.partition(".")
        if head == "self" and self.class_stack:
            return ("__self__", rest.split(".")[0]) if rest else None
        if head == "cls" and self.class_stack:
            return ("__class__", rest.split(".")[0]) if rest else None
        if head in self.alias_map:
            module, name = self.alias_map[head]
            if name:  # from module import name [as head]
                return (module, name) if not rest else (module + "." + name, rest.split(".")[0])
            return (module, rest.split(".")[0]) if rest else (module, "")
        return None

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func)
        if dotted:
            name = dotted.rsplit(".", 1)[-1]
            qualifier = dotted.rsplit(".", 1)[0] if "." in dotted else None
            kind = "instantiate" if name[:1].isupper() and not qualifier else "call"
            self.calls.append(
                CallSite(
                    caller=self._caller(),
                    name=name,
                    qualifier=qualifier,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    kind=kind,
                    hint=self._hint(dotted),
                )
            )
        self.generic_visit(node)


def analyze(key: str, text: str, language: str | None = LANGUAGE) -> FileAnalysis:
    lines = text.split("\n")
    n_lines = len(lines) - (1 if text.endswith("\n") else 0)
    result = FileAnalysis(
        key=key,
        language=LANGUAGE,
        tier="A",
        adapter=PLUGIN_ID,
        adapter_version=PLUGIN_VERSION,
        n_lines=max(n_lines, 0),
    )
    try:
        tree = ast.parse(text, filename=key)
    except SyntaxError as exc:
        # Fall back to the lexical analyzer rather than lose the file; say so.
        fallback = lexical.analyze(key, text, LANGUAGE)
        fallback.notes.append(
            f"python syntax error at line {exc.lineno}: {exc.msg}; lexical analysis used"
        )
        return fallback
    collector = _Collector(key, lines)
    collector.visit(tree)
    stem = key.rsplit("/", 1)[-1]
    stem = stem[: stem.rfind(".")] if "." in stem[1:] else stem
    module_calls = any(c.caller is None for c in collector.calls)
    if module_calls or not collector.symbols:
        doc = _doc(tree)
        content = "\n".join(line.rstrip() for line in lines)
        collector.symbols.append(
            Symbol(
                name=stem,
                qualname="(file)",
                kind="module",
                line=1,
                end_line=max(n_lines, 1),
                end_exact=True,
                signature=f"module {stem}",
                doc=doc,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
        )
        for c in collector.calls:
            if c.caller is None:
                c.caller = "(file)"
    # Regions (cell markers) still come from the lexical profile.
    for region in (s for s in lexical.analyze(key, text, LANGUAGE).symbols if s.kind == "region"):
        collector.symbols.append(region)
    result.symbols = sorted(collector.symbols, key=lambda s: (s.line, s.qualname))
    result.calls = collector.calls
    result.imports = collector.imports
    return result
