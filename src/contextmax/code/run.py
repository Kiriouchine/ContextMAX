# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Stage 2: code analysis. Per file: tier A plugin, else tier B grammar, else tier C lexical;
results cached by content hash so rebuilds are cheap and byte-identical to a full build."""

from __future__ import annotations

import contextlib
import dataclasses
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from contextmax.code import lexical, plugins, treesitter
from contextmax.code.base import CallSite, FileAnalysis, Import, Symbol
from contextmax.code.resolve import resolve_project
from contextmax.fs import os_path, read_text
from contextmax.io.atomic import atomic_write_text
from contextmax.io.hash import sha256_bytes
from contextmax.io.jsonl import write_jsonl
from contextmax.model.nodes import skipped_row
from contextmax.registry import language_name

ANALYSABLE_FAMILIES = ("code", "text")
CACHE_SCHEMA = 1


def choose_analyzer(row: dict[str, Any]) -> tuple[str, str, str, Any]:
    """Return (tier, adapter id, adapter version, callable) for a discovery row."""
    language = row.get("language")
    plugin = row.get("plugin")
    if plugin and plugin in plugins.AVAILABLE:
        fn = plugins.analyzer(plugin)
        if fn is not None:
            adapter = plugins.adapter_id(plugin) or plugin
            return "A", adapter, "1", lambda key, text: fn(key, text, language)
    usable, grammar = treesitter.available_for(language)
    if usable and grammar:
        return (
            "B",
            treesitter.ADAPTER_ID,
            treesitter.ADAPTER_VERSION,
            lambda key, text: treesitter.analyze(key, text, language, grammar),
        )
    return (
        "C",
        lexical.ADAPTER_ID,
        lexical.ADAPTER_VERSION,
        lambda key, text: lexical.analyze(key, text, language),
    )


def _cache_path(cache_dir: Path, sha256: str, adapter: str, version: str) -> Path:
    return cache_dir / f"{sha256}.{adapter}.{version}.json"


def _to_json(analysis: FileAnalysis) -> dict[str, Any]:
    return {"schema": CACHE_SCHEMA, "analysis": dataclasses.asdict(analysis)}


def _from_json(data: dict[str, Any]) -> FileAnalysis | None:
    if data.get("schema") != CACHE_SCHEMA:
        return None
    a = data["analysis"]
    calls = []
    for c in a["calls"]:
        hint = tuple(c["hint"]) if c.get("hint") else None
        calls.append(CallSite(**{**c, "hint": hint}))
    return FileAnalysis(
        key=a["key"],
        language=a["language"],
        tier=a["tier"],
        adapter=a["adapter"],
        adapter_version=a["adapter_version"],
        n_lines=a["n_lines"],
        symbols=[Symbol(**s) for s in a["symbols"]],
        calls=calls,
        imports=[Import(**i) for i in a["imports"]],
        errors=list(a.get("errors", [])),
        notes=list(a.get("notes", [])),
    )


def _tier_b_batch(
    entries: list[dict[str, Any]], log
) -> tuple[dict[str, FileAnalysis], dict[str, str], list[str]]:
    """Parse tier B files in a worker process; returns (analyses, errors, crashed keys)."""
    import os
    import subprocess
    import sys

    from contextmax import grammars

    analyses: dict[str, FileAnalysis] = {}
    errors: dict[str, str] = {}
    crashed: list[str] = []
    remaining = list(entries)
    restarts = 0
    while remaining:
        payload = json.dumps({"grammar_dir": str(grammars.grammar_dir()), "files": remaining})
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "-m", "contextmax.code.tsworker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(payload)
        proc.stdin.close()
        current: str | None = None
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if "start" in record:
                current = record["start"]
            elif "done" in record:
                key = record["done"]
                current = None
                if "analysis" in record:
                    parsed = _from_json({"schema": CACHE_SCHEMA, "analysis": record["analysis"]})
                    if parsed is not None:
                        analyses[key] = parsed
                    else:
                        errors[key] = "worker returned an unreadable analysis"
                else:
                    errors[key] = record.get("error", "unknown worker error")
        stderr = proc.stderr.read() if proc.stderr else ""
        code = proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
        done = set(analyses) | set(errors)
        remaining = [e for e in remaining if e["key"] not in done]
        if code == 0:
            for e in remaining:  # finished cleanly but silently skipped: treat as error
                errors[e["key"]] = "worker ended without a result"
            break
        if current is not None:
            crashed.append(current)
            remaining = [e for e in remaining if e["key"] != current]
            log(
                f"  grammar worker crashed on {current} (exit {code}); lexical analysis used for it"
            )
            restarts += 1
            if restarts > 50:
                for e in remaining:
                    errors[e["key"]] = "too many worker crashes; lexical analysis used"
                break
            continue
        for e in remaining:  # died before starting any file: the grammar layer is unusable
            errors[e["key"]] = (
                f"grammar worker failed to start (exit {code}): {stderr.strip()[-200:]}"
            )
        break
    return analyses, errors, crashed


def analyse_files(
    root: Path,
    roots_of: dict[str, Path],
    files: list[dict[str, Any]],
    cache_dir: Path | None,
    use_cache: bool,
    log,
) -> tuple[list[FileAnalysis], list[str], dict[str, Any]]:
    analyses: list[FileAnalysis] = []
    problems: list[str] = []
    stats: dict[str, Any] = {
        "cache_hits": 0,
        "cache_misses": 0,
        "tier_a": 0,
        "tier_b": 0,
        "tier_c": 0,
        "crashed": [],
    }
    pending: list[tuple[dict[str, Any], str, str, str, Any, Path | None]] = []
    for row in files:
        if row["tier"] not in ("A", "B", "C") or row["content_family"] not in ANALYSABLE_FAMILIES:
            continue
        tier, adapter, version, fn = choose_analyzer(row)
        cache_file = (
            _cache_path(cache_dir, row["sha256"], adapter, version)
            if (cache_dir and row.get("sha256"))
            else None
        )
        analysis: FileAnalysis | None = None
        if use_cache and cache_file is not None and cache_file.is_file():
            try:
                analysis = _from_json(json.loads(cache_file.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError, KeyError):
                analysis = None
            if analysis is not None and analysis.key != row["file"]:
                analysis = None  # same bytes under another path: identity differs, recompute
        if analysis is not None:
            stats["cache_hits"] += 1
            stats[f"tier_{analysis.tier.lower()}"] += 1
            analyses.append(analysis)
            continue
        stats["cache_misses"] += 1
        pending.append((row, tier, adapter, version, fn, cache_file))

    # Tier B goes through the worker in one batch; A and C run in-process.
    batch = [
        {
            "key": row["file"],
            "path": str(_path_for(root, roots_of, row["file"])),
            "language": row.get("language"),
            "grammar": treesitter.available_for(row.get("language"))[1],
        }
        for row, tier, _a, _v, _fn, _c in pending
        if tier == "B"
    ]
    b_results: dict[str, FileAnalysis] = {}
    b_errors: dict[str, str] = {}
    if batch:
        b_results, b_errors, crashed = _tier_b_batch(batch, log)
        stats["crashed"] = crashed
        for key in crashed:
            problems.append(f"{key}: grammar crashed in the parser; lexical analysis used")

    for row, tier, adapter, _version, fn, cache_file in pending:
        analysis = None
        path = _path_for(root, roots_of, row["file"])
        if tier == "B" and row["file"] in b_results:
            analysis = b_results[row["file"]]
        else:
            try:
                text, _encoding = read_text(Path(os_path(path)))
            except OSError as exc:
                problems.append(f"{row['file']}: cannot read ({exc.__class__.__name__})")
                continue
            if tier == "B":
                reason = b_errors.get(row["file"], "grammar crashed")
                analysis = lexical.analyze(row["file"], text, row.get("language"))
                analysis.notes.append(
                    f"{treesitter.ADAPTER_ID} failed: {reason}; lexical analysis used"
                )
                if row["file"] not in stats["crashed"]:
                    problems.append(
                        f"{row['file']}: {treesitter.ADAPTER_ID} failed ({reason}); lexical analysis used"
                    )
            else:
                try:
                    analysis = fn(row["file"], text)
                except Exception as exc:  # a single pathological file must not sink the stage
                    problems.append(
                        f"{row['file']}: {adapter} failed ({exc.__class__.__name__}: {exc}); lexical analysis used"
                    )
                    try:
                        analysis = lexical.analyze(row["file"], text, row.get("language"))
                        analysis.notes.append(f"{adapter} failed: {exc.__class__.__name__}")
                    except Exception as inner:
                        analysis = FileAnalysis(
                            key=row["file"],
                            language=row.get("language"),
                            tier="C",
                            adapter=lexical.ADAPTER_ID,
                            adapter_version=lexical.ADAPTER_VERSION,
                            n_lines=row.get("lines") or 0,
                            errors=[f"{inner.__class__.__name__}: {inner}"],
                        )
        if cache_file is not None and analysis.tier == tier:
            # Only a result of the intended tier is cached; a fallback is recomputed next time.
            with contextlib.suppress(OSError):
                atomic_write_text(
                    cache_file, json.dumps(_to_json(analysis), sort_keys=True, ensure_ascii=False)
                )
        stats[f"tier_{analysis.tier.lower()}"] += 1
        analyses.append(analysis)
    analyses.sort(key=lambda a: a.key)
    return analyses, problems, stats


def _path_for(root: Path, roots_of: dict[str, Path], key: str) -> Path:
    if key.startswith("ext:"):
        prefix, _, rest = key.partition("/")
        base = roots_of.get(prefix)
        if base is not None:
            return base / rest
    return root / key


def run_code_stage(ctx) -> dict[str, Any]:
    assert ctx.discovery is not None
    from contextmax.discover import resolve_roots

    roots_of = {
        r.prefix: r.path for r in resolve_roots(ctx.root, ctx.config) if r.prefix.startswith("ext:")
    }
    use_cache = not ctx.options.get("full", False)
    analyses, problems, cache_stats = analyse_files(
        ctx.root, roots_of, ctx.discovery.files, ctx.layout.cache_dir, use_cache, ctx.log
    )
    # The tier a file actually got may differ from discovery's guess (a plugin fell back, or a
    # grammar was provisioned since); the file rows are corrected so every artifact agrees.
    tier_of = {a.key: a.tier for a in analyses}
    changed = False
    for row in ctx.discovery.files:
        if row["file"] in tier_of and row["tier"] != tier_of[row["file"]]:
            row["tier"] = tier_of[row["file"]]
            changed = True
    if changed:
        ctx.artifacts["nodes/files.jsonl"] = write_jsonl(
            ctx.layout.files_jsonl, ctx.discovery.files
        )
        counts = ctx.discovery.counts
        counts["by_tier"] = {}
        for row in ctx.discovery.files:
            counts["by_tier"][row["tier"]] = counts["by_tier"].get(row["tier"], 0) + 1
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
    for key in cache_stats.get("crashed", []):
        ctx.extra_skipped.append(
            skipped_row(
                key=key,
                reason_code="grammar-crash",
                reason="the tree-sitter grammar crashed on this file; lexical analysis used",
                size=None,
                detected_as=next(
                    (r.get("language") for r in ctx.discovery.files if r["file"] == key), None
                ),
            )
        )
    # Cache statistics describe this run, not the project: they go to the ledger, not coverage.
    ctx.state.mark(
        "code", note=f"cache hits {cache_stats['cache_hits']}, misses {cache_stats['cache_misses']}"
    )
    ctx.log(
        f"  {len(result['symbols'])} symbols in {len(analyses)} files (tier A {cache_stats['tier_a']}, "
        f"B {cache_stats['tier_b']}, C {cache_stats['tier_c']}; cache hits {cache_stats['cache_hits']}); "
        f"{stats.n_call_sites} call sites: {stats.n_resolved} resolved to project symbols, "
        f"{stats.n_ambiguous} ambiguous, {stats.n_external} to libraries or builtins, "
        f"{stats.n_unresolved} to names not defined in the project; "
        f"{stats.n_imports_resolved} of {stats.n_imports} imports resolved"
    )
    for lang, bucket in sorted(stats.by_language.items()):
        if bucket["n_call_sites"]:
            ctx.log(
                f"    {language_name(lang) or lang}: {bucket['n_resolved']} resolved, "
                f"{bucket['n_ambiguous']} ambiguous, {bucket['n_external']} library, "
                f"{bucket['n_unresolved']} unknown of {bucket['n_call_sites']}"
            )
    adapters_used: dict[str, dict[str, Any]] = {}
    for a in analyses:
        entry = adapters_used.setdefault(
            a.adapter,
            {
                "version": a.adapter_version,
                "determinism": "version-bound" if a.tier == "B" else "intrinsic",
                "tier": a.tier,
                "n": 0,
            },
        )
        entry["n"] += 1
    if treesitter.ADAPTER_ID in adapters_used:
        from contextmax import grammars

        adapters_used[treesitter.ADAPTER_ID]["pack_version"] = grammars.pack_version()
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
        "by_tier": {
            "A": cache_stats["tier_a"],
            "B": cache_stats["tier_b"],
            "C": cache_stats["tier_c"],
        },
        "adapters": adapters_used,
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
        "Generated by ContextMAX. Tier A rows come from a language plugin, tier B from a syntax grammar,",
        "tier C from lexical patterns (confidence low). Verify at the cited lines. Counts are exact even",
        "where tables are capped.",
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
            "| Symbol | Kind | Tier | Signature | Doc | Callers | Calls | Where |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in rows[:cap_per_module]:
            doc = (row["doc"] or "").replace("|", "\\|")
            doc = doc[:120] + ("…" if len(doc) > 120 else "")
            sig = (row["signature"] or "").replace("|", "\\|")
            sig = sig[:100] + ("…" if len(sig) > 100 else "")
            callees = ", ".join(sorted(set(callee_names.get(row["id"], [])))[:8])
            label = row["name"] if row["qualname"] == "(file)" else row["qualname"]
            lines.append(
                f"| `{label}` | {row['kind']} | {row['tier']} | `{sig}` | {doc} | {row['n_callers']} | {callees} | `{row['cite']}` |"
            )
        if len(rows) > cap_per_module:
            lines.append(
                f"| … | | | | {len(rows) - cap_per_module} more symbols not shown; all are in `nodes/symbols.jsonl` | | | |"
            )
        lines.append("")
    return "\n".join(lines)
