# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Stage 2: code analysis over every file discovery marked readable, then project-wide resolution."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from contextmax.code import lexical
from contextmax.code.base import FileAnalysis
from contextmax.code.resolve import resolve_project
from contextmax.fs import os_path, read_text
from contextmax.io.atomic import atomic_write_text
from contextmax.io.hash import sha256_bytes
from contextmax.io.jsonl import write_jsonl
from contextmax.registry import language_name

ANALYSABLE_FAMILIES = ("code", "text")


def analyse_files(
    root: Path, roots_of: dict[str, Path], files: list[dict[str, Any]], log
) -> tuple[list[FileAnalysis], list[str]]:
    analyses: list[FileAnalysis] = []
    problems: list[str] = []
    for row in files:
        if row["tier"] not in ("B", "C") or row["content_family"] not in ANALYSABLE_FAMILIES:
            continue
        path = _path_for(root, roots_of, row["file"])
        try:
            text, _encoding = read_text(Path(os_path(path)))
        except OSError as exc:
            problems.append(f"{row['file']}: cannot read ({exc.__class__.__name__})")
            continue
        try:
            analysis = lexical.analyze(row["file"], text, row["language"])
        except Exception as exc:  # a single pathological file must not sink the stage
            problems.append(
                f"{row['file']}: lexical analysis failed ({exc.__class__.__name__}: {exc})"
            )
            analysis = FileAnalysis(
                key=row["file"],
                language=row["language"],
                tier="C",
                adapter=lexical.ADAPTER_ID,
                adapter_version=lexical.ADAPTER_VERSION,
                n_lines=row.get("lines") or 0,
                errors=[str(exc)],
            )
        analyses.append(analysis)
    return analyses, problems


def _path_for(root: Path, roots_of: dict[str, Path], key: str) -> Path:
    if key.startswith("ext:"):
        prefix, _, rest = key.partition("/")
        base = roots_of.get(prefix)
        if base is not None:
            return base / rest
    return root / key


def run_code_stage(ctx) -> dict[str, Any]:
    assert ctx.discovery is not None
    from contextmax.discover import resolve_roots  # local import keeps the stage module light

    roots_of = {
        r.prefix: r.path for r in resolve_roots(ctx.root, ctx.config) if r.prefix.startswith("ext:")
    }
    analyses, problems = analyse_files(ctx.root, roots_of, ctx.discovery.files, ctx.log)
    role_of = {row["file"]: row["role"] for row in ctx.discovery.files}
    adapter_of = {a.key: a.adapter for a in analyses}
    result = resolve_project(analyses, role_of, adapter_of)
    layout = ctx.layout
    ctx.artifacts["nodes/symbols.jsonl"] = write_jsonl(
        layout.nodes / "symbols.jsonl", result["symbols"]
    )
    ctx.artifacts["edges/calls.jsonl"] = write_jsonl(
        layout.edges / "calls.jsonl", result["calls"], key=_edge_key
    )
    ctx.artifacts["edges/imports.jsonl"] = write_jsonl(
        layout.edges / "imports.jsonl", result["imports"], key=_edge_key
    )
    ctx.artifacts["edges/contains.jsonl"] = write_jsonl(
        layout.edges / "contains.jsonl", result["contains"], key=_edge_key
    )
    stats = result["stats"]
    codemap = render_codemap(result["symbols"], result["calls"])
    ctx.artifacts["CODEMAP.md"] = sha256_bytes(
        atomic_write_text(layout.index / "CODEMAP.md", codemap)
    )
    for problem in problems:
        ctx.problems.append(f"code: {problem}")
    ctx.log(
        f"  {len(result['symbols'])} symbols in {len(analyses)} files; {stats.n_call_sites} call sites: "
        f"{stats.n_resolved} resolved to project symbols, {stats.n_ambiguous} ambiguous, "
        f"{stats.n_external} to libraries or builtins, {stats.n_unresolved} to names not defined in the project; "
        f"{stats.n_imports_resolved} of {stats.n_imports} imports resolved"
    )
    for lang, bucket in sorted(stats.by_language.items()):
        if bucket["n_call_sites"]:
            ctx.log(
                f"    {language_name(lang) or lang}: {bucket['n_resolved']} resolved, {bucket['n_ambiguous']} ambiguous, "
                f"{bucket['n_external']} library, {bucket['n_unresolved']} unknown of {bucket['n_call_sites']}"
            )
    return {
        "n_files_analysed": len(analyses),
        "n_symbols": len(result["symbols"]),
        "n_call_sites": stats.n_call_sites,
        "n_resolved": stats.n_resolved,
        "n_ambiguous": stats.n_ambiguous,
        "n_unresolved": stats.n_unresolved,
        "n_external": stats.n_external,
        "n_bare_dropped": stats.n_bare_dropped,
        "n_index_dropped": stats.n_index_dropped,
        "n_imports": stats.n_imports,
        "n_imports_resolved": stats.n_imports_resolved,
        "by_language": dict(sorted(stats.by_language.items())),
        "adapters": {
            lexical.ADAPTER_ID: {
                "version": lexical.ADAPTER_VERSION,
                "determinism": "intrinsic",
                "tier": "C",
            }
        },
    }


def _edge_key(row: dict[str, Any]) -> tuple:
    return (
        row["src"],
        row["dst"] or "",
        row.get("dst_name") or "",
        row["rel"],
        row.get("kind") or "",
    )


def render_codemap(
    symbols: list[dict[str, Any]], calls: list[dict[str, Any]], cap_per_module: int = 300
) -> str:
    """CODEMAP.md: one section per folder with a symbol table, for people and agents alike."""
    by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in symbols:
        if row["kind"] == "region":
            continue
        folder = row["file"].rsplit("/", 1)[0] if "/" in row["file"] else "(root)"
        by_module[folder].append(row)
    name_of = {
        row["id"]: row["qualname"] if row["qualname"] != "(file)" else row["name"]
        for row in symbols
    }
    callee_names: dict[str, list[str]] = defaultdict(list)
    for edge in calls:
        if edge["status"] == "resolved" and edge["dst"]:
            callee_names[edge["src"]].append(name_of.get(edge["dst"], edge["dst"]))
    lines = [
        "# Code map",
        "",
        "Generated by ContextMAX. Tier C rows come from lexical analysis: definitions and calls found by",
        "pattern, confidence low. Verify at the cited lines. Counts are exact even where tables are capped.",
        "",
    ]
    for folder in sorted(by_module):
        rows = sorted(
            by_module[folder], key=lambda r: (r["file"], r["span"]["start"], r["qualname"])
        )
        lines += [
            f"## {folder}",
            "",
            f"{len(rows)} symbols in {len({r['file'] for r in rows})} files.",
            "",
            "| Symbol | Kind | Signature | Doc | Callers | Calls | Where |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in rows[:cap_per_module]:
            doc = (row["doc"] or "").replace("|", "\\|")
            doc = doc[:120] + ("…" if len(doc) > 120 else "")
            sig = (row["signature"] or "").replace("|", "\\|")
            sig = sig[:100] + ("…" if len(sig) > 100 else "")
            callees = ", ".join(sorted(set(callee_names.get(row["id"], [])))[:8])
            label = row["name"] if row["qualname"] == "(file)" else row["qualname"]
            lines.append(
                f"| `{label}` | {row['kind']} | `{sig}` | {doc} | {row['n_callers']} | {callees} | `{row['cite']}` |"
            )
        if len(rows) > cap_per_module:
            lines.append(
                f"| … | | | {len(rows) - cap_per_module} more symbols not shown; all are in `nodes/symbols.jsonl` | | | |"
            )
        lines.append("")
    return "\n".join(lines)
