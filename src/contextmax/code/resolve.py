# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Project-wide resolution of call sites and imports, with ambiguity kept visible.

Order for a call: plugin resolver (tier A, later), same file, same folder, unique name
project-wide, file named like the callee (MATLAB and other file-per-function languages), else
ambiguous with every candidate listed, external when the qualifier matches a non-project
import, else unresolved. Bare calls (a lone word on a line, a shell command) are gated: they
become edges only when they resolve to a symbol in the same file or uniquely project-wide, and
are otherwise dropped, because recording every word as unresolved would drown the report.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from contextmax.code import lexical
from contextmax.code.base import CallSite, FileAnalysis, Import, Symbol
from contextmax.io.canon import parent_key, rel_key
from contextmax.model.edges import edge_row
from contextmax.model.ids import file_id, sym_id

CALLABLE_KINDS = frozenset(
    {
        "function",
        "method",
        "constructor",
        "macro",
        "script",
        "module",
        "task",
        "target",
        "entity",
        "component",
        "class",
        "struct",
        "type",
        "stage",
        "resource",
    }
)

_LANGUAGE_EXTS: dict[str, tuple[str, ...]] = {
    "python": (".py", "/__init__.py"),
    "javascript": (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", "/index.js", "/index.ts", ".json"),
    "typescript": (".ts", ".tsx", ".js", ".mjs", "/index.ts", "/index.js", ".json"),
    "tsx": (".tsx", ".ts", ".js", "/index.tsx", "/index.ts"),
    "c": (".h", ".c", ".hpp"),
    "cpp": (".hpp", ".h", ".hh", ".hxx", ".cpp", ".cc"),
    "matlab": (".m",),
    "shell": (".sh", ".bash", ""),
    "powershell": (".ps1", ".psm1"),
    "batch": (".bat", ".cmd"),
    "go": ("/", ".go"),
    "rust": (".rs", "/mod.rs"),
    "ruby": (".rb",),
    "lua": (".lua", "/init.lua"),
    "r": (".R", ".r"),
    "vhdl": (".vhd", ".vhdl"),
    "verilog": (".v", ".sv", ".vh", ".svh"),
    "make": ("", ".mk"),
    "cmake": (".cmake", "/CMakeLists.txt"),
    "fortran": (".f90", ".f", ".mod"),
    "pascal": (".pas", ".pp"),
    "perl": (".pm", ".pl"),
}


@dataclass
class SymbolRef:
    key: str
    symbol: Symbol
    id: str
    language: str | None


@dataclass
class ResolutionStats:
    n_call_sites: int = 0
    n_resolved: int = 0
    n_ambiguous: int = 0
    n_unresolved: int = 0
    n_external: int = 0
    n_bare_dropped: int = 0
    n_index_dropped: int = 0
    n_imports: int = 0
    n_imports_resolved: int = 0
    by_language: dict[str, dict[str, int]] = field(default_factory=dict)

    def bump(self, language: str | None, field_name: str, amount: int = 1) -> None:
        lang = language or "text"
        bucket = self.by_language.setdefault(
            lang,
            {
                "n_call_sites": 0,
                "n_resolved": 0,
                "n_ambiguous": 0,
                "n_unresolved": 0,
                "n_external": 0,
            },
        )
        bucket[field_name] = bucket.get(field_name, 0) + amount
        setattr(self, field_name, getattr(self, field_name) + amount)


class ProjectIndex:
    """Lookup tables over every analysed file."""

    def __init__(self, analyses: list[FileAnalysis]) -> None:
        self.analyses = analyses
        self.by_key: dict[str, FileAnalysis] = {a.key: a for a in analyses}
        self.file_keys: set[str] = set(self.by_key)
        self.refs: list[SymbolRef] = []
        self.by_name: dict[str, list[SymbolRef]] = defaultdict(list)
        self.by_qualname: dict[str, list[SymbolRef]] = defaultdict(list)
        self.by_id: dict[str, SymbolRef] = {}
        self.file_symbol: dict[str, SymbolRef] = {}
        self.by_stem: dict[str, list[SymbolRef]] = defaultdict(list)
        for analysis in analyses:
            ordinals: dict[str, int] = {}
            for sym in analysis.symbols:
                ordinals[sym.qualname] = ordinals.get(sym.qualname, 0) + 1
                ident = sym_id(analysis.key, sym.qualname, ordinals[sym.qualname])
                ref = SymbolRef(key=analysis.key, symbol=sym, id=ident, language=analysis.language)
                self.refs.append(ref)
                self.by_id[ident] = ref
                if sym.kind == "region":
                    continue
                self.by_name[sym.name].append(ref)
                self.by_qualname[sym.qualname].append(ref)
                if sym.qualname == "(file)":
                    self.file_symbol[analysis.key] = ref
            stem = analysis.key.rsplit("/", 1)[-1]
            stem = stem[: stem.rfind(".")] if "." in stem[1:] else stem
            # The symbol a file "is": its top-level definition named like the file, else its file symbol.
            named = [
                r
                for r in self.refs
                if r.key == analysis.key
                and r.symbol.name == stem
                and r.symbol.parent is None
                and r.symbol.kind in CALLABLE_KINDS
                and r.symbol.qualname != "(file)"
            ]
            if named:
                self.by_stem[stem].append(named[0])
            elif analysis.key in self.file_symbol:
                self.by_stem[stem].append(self.file_symbol[analysis.key])

    def symbol_ids_in(self, key: str) -> list[str]:
        return [r.id for r in self.refs if r.key == key]


def _narrow(
    cands: list[SymbolRef], key: str
) -> tuple[SymbolRef | None, str | None, list[SymbolRef]]:
    """Return (winner, evidence, candidates) applying same-file then same-folder narrowing."""
    callable_cands = [c for c in cands if c.symbol.kind in CALLABLE_KINDS] or cands
    non_file = [c for c in callable_cands if c.symbol.qualname != "(file)"]
    if non_file:
        callable_cands = non_file  # a real definition beats the file that merely bears the name
    if len(callable_cands) == 1:
        return callable_cands[0], "unique-name", callable_cands
    same_file = [c for c in callable_cands if c.key == key]
    if len(same_file) == 1:
        return same_file[0], "same-file", callable_cands
    folder = parent_key(key)
    same_folder = [c for c in callable_cands if parent_key(c.key) == folder]
    if len(same_folder) == 1:
        return same_folder[0], "same-folder", callable_cands
    return None, None, callable_cands


def resolve_import_target(
    index: ProjectIndex, importer_key: str, imp: Import, language: str | None
) -> str | None:
    module = imp.module.strip().strip("'\"<>")
    if not module:
        return None
    variants: list[str] = []
    dotted = module
    if language in ("python", "java", "csharp", "kotlin", "scala") and "/" not in module:
        dotted = module.replace(".", "/")
    if language == "rust":
        dotted = module.replace("::", "/")
    dotted = rel_key(dotted)
    base_dirs = [parent_key(importer_key)]
    parts = base_dirs[0].split("/") if base_dirs[0] else []
    for depth in range(len(parts), -1, -1):
        base_dirs.append("/".join(parts[:depth]))
    if imp.relative or module.startswith("./") or module.startswith("../"):
        rel = module
        base = parent_key(importer_key)
        if language == "python":
            dots = len(module) - len(module.lstrip("."))
            rel = module.lstrip(".").replace(".", "/")
            for _ in range(max(dots - 1, 0)):
                base = parent_key(base)
        variants.append(rel_key(f"{base}/{rel}") if base else rel_key(rel))
    else:
        seen: set[str] = set()
        for base in base_dirs:
            cand = rel_key(f"{base}/{dotted}") if base else dotted
            if cand not in seen:
                seen.add(cand)
                variants.append(cand)
    exts = _LANGUAGE_EXTS.get(language or "", ("",))
    for variant in variants:
        for ext in (*exts, ""):
            candidate = variant + ext
            candidate = rel_key(candidate)
            if candidate in index.file_keys:
                return candidate
    # Last resort: a unique file anywhere whose name matches the module's last segment.
    leaf = dotted.rsplit("/", 1)[-1]
    matches = sorted(
        k
        for k in index.file_keys
        if k.rsplit("/", 1)[-1] == leaf or k.rsplit("/", 1)[-1].rsplit(".", 1)[0] == leaf
    )
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_project(
    analyses: list[FileAnalysis], role_of: dict[str, str], adapter_of: dict[str, str]
) -> dict[str, Any]:
    """Resolve every call site and import. Returns rows for symbols, calls, imports, contains, and stats."""
    index = ProjectIndex(analyses)
    stats = ResolutionStats()
    call_rows: list[dict[str, Any]] = []
    import_rows: list[dict[str, Any]] = []
    contains_rows: list[dict[str, Any]] = []
    callers: dict[str, set[str]] = defaultdict(set)
    callees: dict[str, set[str]] = defaultdict(set)

    for analysis in analyses:
        language = analysis.language
        adapter = analysis.adapter
        tier = analysis.tier
        # Group call sites per (caller, callee name, qualifier).
        grouped: dict[tuple[str | None, str, str | None, str], list[CallSite]] = defaultdict(list)
        for site in analysis.calls:
            grouped[(site.caller, site.name, site.qualifier, site.kind)].append(site)
        for (caller_q, name, qualifier, kind), sites in sorted(
            grouped.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], str(kv[0][2]), kv[0][3])
        ):
            src_ref = _caller_ref(index, analysis.key, caller_q)
            if src_ref is None:
                continue
            n_sites = len(sites)
            site_dicts = [
                {"line": s.line, "col": s.col} for s in sorted(sites, key=lambda s: (s.line, s.col))
            ]
            cands = list(index.by_qualname.get(f"{qualifier}.{name}", [])) if qualifier else []
            evidence = "qualified-name" if cands else None
            if not cands:
                cands = list(index.by_name.get(name, []))
            winner, ev, cands = _narrow(cands, analysis.key) if cands else (None, None, [])
            evidence = evidence or ev
            if winner is None and not cands:
                stem_refs = index.by_stem.get(name, [])
                if len(stem_refs) == 1:
                    winner, evidence = stem_refs[0], "file-name"
                elif len(stem_refs) > 1:
                    cands = stem_refs
            if winner is not None and winner.id == src_ref.id and kind != "bare":
                evidence = "recursion"
            elif winner is not None and winner.symbol.qualname == "(file)":
                evidence = "file-name"
            if kind == "bare" and winner is None:
                stats.n_bare_dropped += n_sites
                continue
            if kind == "index":
                if winner is None and not cands:
                    stats.n_index_dropped += n_sites
                    continue
                evidence = f"{evidence}+index-or-call" if evidence else "index-or-call"
            stats.bump(language, "n_call_sites", n_sites)
            rel = "instantiates" if kind == "instantiate" else "calls"
            if winner is not None:
                stats.bump(language, "n_resolved", n_sites)
                callers[winner.id].add(src_ref.id)
                callees[src_ref.id].add(winner.id)
                call_rows.append(
                    edge_row(
                        src=src_ref.id,
                        dst=winner.id,
                        rel=rel,
                        tier=tier,
                        confidence="low",
                        evidence=f"lexical:{evidence}",
                        adapter=adapter,
                        status="resolved",
                        dst_name=name,
                        count=n_sites,
                        sites=site_dicts,
                        kind=kind,
                    )
                )
            elif cands:
                stats.bump(language, "n_ambiguous", n_sites)
                call_rows.append(
                    edge_row(
                        src=src_ref.id,
                        dst=None,
                        rel=rel,
                        tier=tier,
                        confidence="low",
                        evidence="lexical:ambiguous",
                        adapter=adapter,
                        status="ambiguous",
                        dst_name=(f"{qualifier}.{name}" if qualifier else name),
                        count=n_sites,
                        sites=site_dicts,
                        candidates=[c.id for c in cands],
                        kind=kind,
                    )
                )
            else:
                prof = lexical.profile_for(language)
                head = qualifier.split(".", 1)[0].lower() if qualifier else None
                if name.lower() in prof.builtins or (qualifier or "").lower() in prof.builtins:
                    external, reason = True, "builtin"
                elif head is not None and head in prof.globals_:
                    external, reason = True, "global"
                elif qualifier is not None and _qualifier_is_import(analysis, qualifier):
                    external, reason = True, "import"
                else:
                    external, reason = False, "unresolved"
                status = "external" if external else "unresolved"
                stats.bump(language, "n_external" if external else "n_unresolved", n_sites)
                call_rows.append(
                    edge_row(
                        src=src_ref.id,
                        dst=None,
                        rel=rel,
                        tier=tier,
                        confidence=None,
                        evidence="lexical:" + reason,
                        adapter=adapter,
                        status=status,
                        dst_name=(f"{qualifier}.{name}" if qualifier else name),
                        count=n_sites,
                        sites=site_dicts,
                        kind=kind,
                    )
                )

        for imp in analysis.imports:
            stats.n_imports += 1
            target = resolve_import_target(index, analysis.key, imp, language)
            if target:
                stats.n_imports_resolved += 1
            import_rows.append(
                edge_row(
                    src=file_id(analysis.key),
                    dst=file_id(target) if target else None,
                    rel="imports",
                    tier=tier,
                    confidence="medium" if target else None,
                    evidence=f"lexical:{imp.kind}",
                    adapter=adapter,
                    status="resolved"
                    if target
                    else ("external" if not imp.relative else "unresolved"),
                    dst_name=imp.module,
                    count=1,
                    sites=[{"line": imp.line, "col": 1}],
                    kind=imp.kind,
                )
            )
        # Containment.
        for ref in [r for r in index.refs if r.key == analysis.key]:
            parent = ref.symbol.parent
            if parent is None:
                contains_rows.append(
                    edge_row(
                        src=file_id(analysis.key),
                        dst=ref.id,
                        rel="contains",
                        tier=tier,
                        confidence="high",
                        evidence="lexical:definition",
                        adapter=adapter,
                    )
                )
            else:
                parent_refs = [
                    p for p in index.by_qualname.get(parent, []) if p.key == analysis.key
                ]
                if parent_refs:
                    contains_rows.append(
                        edge_row(
                            src=parent_refs[0].id,
                            dst=ref.id,
                            rel="contains",
                            tier=tier,
                            confidence="high",
                            evidence="lexical:nesting",
                            adapter=adapter,
                        )
                    )

    symbol_rows = [
        _symbol_row(
            ref,
            role_of.get(ref.key, "product"),
            adapter_of.get(ref.key, ""),
            index.by_key[ref.key].tier,
            len(callers.get(ref.id, ())),
            len(callees.get(ref.id, ())),
        )
        for ref in index.refs
    ]
    return {
        "symbols": symbol_rows,
        "calls": call_rows,
        "imports": import_rows,
        "contains": contains_rows,
        "stats": stats,
        "index": index,
    }


def _caller_ref(index: ProjectIndex, key: str, caller_q: str | None) -> SymbolRef | None:
    if caller_q is None or caller_q == "(file)":
        return index.file_symbol.get(key)
    refs = [r for r in index.by_qualname.get(caller_q, []) if r.key == key]
    return refs[0] if refs else index.file_symbol.get(key)


def _qualifier_is_import(analysis: FileAnalysis, qualifier: str) -> bool:
    head = qualifier.split(".", 1)[0]
    for imp in analysis.imports:
        if (
            imp.alias == head
            or imp.module == head
            or imp.module.split(".")[-1] == head
            or head in imp.names
        ):
            return True
        if imp.module.startswith(head + ".") or imp.module.endswith("." + head):
            return True
    return False


def _symbol_row(
    ref: SymbolRef, role: str, adapter: str, tier: str, n_callers: int, n_callees: int
) -> dict[str, Any]:
    s = ref.symbol
    span = {"start": s.line, "end": s.end_line, "end_exact": s.end_exact}
    cite = f"{ref.key}:{s.line}" if s.line == s.end_line else f"{ref.key}:{s.line}-{s.end_line}"
    return {
        "id": ref.id,
        "kind": s.kind,
        "family": "code",
        "name": s.name,
        "qualname": s.qualname,
        "file": ref.key,
        "lang": ref.language,
        "span": span,
        "tier": tier,
        "confidence": "low" if tier == "C" else ("medium" if tier == "B" else "high"),
        "adapter": adapter,
        "signature": s.signature,
        "params": s.params,
        "returns": s.returns,
        "doc": s.doc,
        "decorators": s.decorators,
        "visibility": s.visibility,
        "role": role,
        "parent": sym_id(ref.key, s.parent) if s.parent else None,
        "content_hash": s.content_hash,
        "n_lines": s.end_line - s.line + 1,
        "n_callers": n_callers,
        "n_callees": n_callees,
        "cite": cite,
    }
