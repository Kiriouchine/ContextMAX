# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""The build pipeline: ordered stages, each wrapped, each recorded, manifest last.

A stage failure is collected, not fatal: later stages still run where their inputs exist, and
the run exits non-zero with the list of problems. A build must never look finished when it is
not, because a half-built index that looks complete is the one failure that silently produces
wrong answers.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from contextmax import version
from contextmax.buildstate import STAGES, BuildState
from contextmax.config import Config, load_config
from contextmax.coverage import build_coverage
from contextmax.discover import DiscoveryResult, discover
from contextmax.io.atomic import atomic_write_text
from contextmax.io.jsonl import write_json, write_jsonl
from contextmax.manifest import build_manifest
from contextmax.paths import SKIP_MARKER, Layout, layout_for
from contextmax.registry import format_name, language_name


@dataclass
class Context:
    root: Path
    config: Config
    layout: Layout
    options: dict[str, Any]
    state: BuildState
    discovery: DiscoveryResult | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    code_stats: dict[str, Any] = field(default_factory=dict)
    doc_stats: dict[str, Any] = field(default_factory=dict)
    link_stats: dict[str, Any] = field(default_factory=dict)
    graph_stats: dict[str, Any] = field(default_factory=dict)
    adapters: dict[str, Any] = field(default_factory=dict)
    extra_skipped: list[dict[str, Any]] = field(default_factory=list)
    log: Callable[[str], None] = print


@dataclass(frozen=True)
class Stage:
    name: str
    run: Callable[[Context], None]
    enabled: Callable[[Config], bool] = lambda cfg: True


# --- Stage implementations -----------------------------------------------------------------


def stage_discover(ctx: Context) -> None:
    ctx.discovery = discover(ctx.root, ctx.config, ctx.layout)
    ctx.artifacts["nodes/files.jsonl"] = write_jsonl(ctx.layout.files_jsonl, ctx.discovery.files)
    ctx.artifacts["skipped.jsonl"] = write_jsonl(
        ctx.layout.skipped, ctx.discovery.skipped, key=lambda r: (r["file"], r["reason_code"])
    )
    c = ctx.discovery.counts
    ctx.log(
        f"  {c['n_files']} files in {c['n_dirs']} folders; tiers "
        + ", ".join(f"{t}={c['by_tier'].get(t, 0)}" for t in "ABCD")
        + f"; {c['n_skipped']} recorded skips; {c['n_excluded_dirs']} folders and "
        f"{c['n_excluded_files']} files excluded by rules"
    )


def stage_code(ctx: Context) -> None:
    from contextmax.code.run import run_code_stage

    stats = run_code_stage(ctx)
    ctx.adapters.update(stats.pop("adapters", {}))
    ctx.code_stats = stats


def stage_documents(ctx: Context) -> None:
    from contextmax.docs.run import run_documents_stage

    stats = run_documents_stage(ctx)
    ctx.adapters.update(stats.pop("adapters", {}))
    ctx.doc_stats = stats


def stage_links(ctx: Context) -> None:
    from contextmax.link.run import run_links_stage

    ctx.link_stats = run_links_stage(ctx)


def stage_graph(ctx: Context) -> None:
    from contextmax.graph.build import run_graph_stage

    ctx.graph_stats = run_graph_stage(ctx)


def stage_query(ctx: Context) -> None:
    from contextmax.query.store import run_query_stage

    run_query_stage(ctx)


def stage_viz(ctx: Context) -> None:
    from contextmax.viz.render import run_viz_stage

    run_viz_stage(ctx)


def stage_skill(ctx: Context) -> None:
    from contextmax.skill.render import run_skill_stage

    run_skill_stage(ctx)


def _coverage_extra(ctx: Context) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if ctx.code_stats:
        extra["code"] = dict(ctx.code_stats)
    if ctx.doc_stats:
        extra["documents"] = dict(ctx.doc_stats)
    if ctx.link_stats:
        extra["links"] = dict(ctx.link_stats)
    if ctx.graph_stats:
        extra["graph"] = dict(ctx.graph_stats)
    return extra


def stage_catalogs(ctx: Context) -> None:
    assert ctx.discovery is not None
    if ctx.extra_skipped:
        # Later stages found files that could not be read; the one skip list carries them too.
        ctx.discovery.skipped.extend(ctx.extra_skipped)
        counts = ctx.discovery.counts
        for row in ctx.extra_skipped:
            counts["by_skip_reason"][row["reason_code"]] = (
                counts["by_skip_reason"].get(row["reason_code"], 0) + 1
            )
        counts["n_skipped"] = len(ctx.discovery.skipped)
        ctx.extra_skipped = []
        ctx.artifacts["skipped.jsonl"] = write_jsonl(
            ctx.layout.skipped, ctx.discovery.skipped, key=lambda r: (r["file"], r["reason_code"])
        )
    ctx.coverage = build_coverage(ctx.discovery.counts, _coverage_extra(ctx))
    ctx.artifacts["coverage.json"] = write_json(ctx.layout.coverage, ctx.coverage)
    ctx.artifacts["INDEX.md"] = _write_index_md(ctx)
    _write_index_readme(ctx)


def stage_manifest(ctx: Context) -> None:
    assert ctx.discovery is not None
    if not ctx.coverage:
        ctx.coverage = build_coverage(ctx.discovery.counts, _coverage_extra(ctx))
    manifest = build_manifest(
        layout=ctx.layout,
        config=ctx.config,
        files=ctx.discovery.files,
        build_state=ctx.state.data,
        coverage=ctx.coverage,
        adapters=ctx.adapters,
    )
    write_json(ctx.layout.manifest, manifest)
    ctx.log(
        f"  baseline {manifest['baseline_identity_hash'][:12]}  artifact "
        f"{manifest['artifact_identity_hash'][:12]}  completeness {manifest['completeness']['verdict']}"
    )


def _write_index_md(ctx: Context) -> str:
    cov = ctx.coverage
    cfg = ctx.config
    lines = [
        f"# {cfg.name} — ContextMAX index",
        "",
        "This folder is a deterministic index of the project, generated by ContextMAX with no",
        "AI involved. Use it as a fast way in; verify every claim at the cited source.",
        "",
        "## Size",
        "",
        "| Files | Folders | Tier A | Tier B | Tier C | Tier D | Recorded skips |",
        "|---|---|---|---|---|---|---|",
        f"| {cov['n_files']} | {cov['n_dirs']} | {cov['by_tier']['A']} | {cov['by_tier']['B']} | "
        f"{cov['by_tier']['C']} | {cov['by_tier']['D']} | {cov['n_skipped']} |",
        "",
        "Tiers: A = dedicated analyzer, B = generic grammar, C = lexical only, D = catalogued only.",
        "",
    ]
    if cov["by_language"]:
        lines += ["## Languages", "", "| Language | Files |", "|---|---|"]
        for lang, count in sorted(cov["by_language"].items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| {language_name(lang)} | {count} |")
        lines.append("")
    if cov["by_format"]:
        lines += ["## Document and data formats", "", "| Format | Files |", "|---|---|"]
        for fmt, count in sorted(cov["by_format"].items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| {format_name(fmt)} | {count} |")
        lines.append("")
    folders: dict[str, int] = {}
    assert ctx.discovery is not None
    for row in ctx.discovery.files:
        top = row["file"].split("/", 1)[0] if "/" in row["file"] else "(root)"
        folders[top] = folders.get(top, 0) + 1
    lines += ["## Top-level folders", "", "| Folder | Files |", "|---|---|"]
    for folder, count in sorted(folders.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {folder} | {count} |")
    lines.append("")
    code = cov.get("code", {})
    if code.get("n_symbols"):
        n_sites = code.get("n_call_sites", 0)
        pct = (100.0 * code.get("n_resolved", 0) / n_sites) if n_sites else 0.0
        lines += [
            "## Code",
            "",
            f"{code['n_symbols']} symbols in {code.get('n_files_analysed', 0)} analysed files. "
            f"{code.get('n_resolved', 0)} of {n_sites} call sites resolve inside the project ({pct:.0f}%); "
            f"{code.get('n_ambiguous', 0)} ambiguous, {code.get('n_external', 0)} to libraries, "
            f"{code.get('n_unresolved', 0)} to names not defined in the project. Details per symbol in `CODEMAP.md`.",
            "",
        ]
        symbols_path = ctx.layout.nodes / "symbols.jsonl"
        if symbols_path.is_file():
            from contextmax.io.jsonl import read_jsonl

            symbols = [
                s
                for s in read_jsonl(symbols_path)
                if s["kind"] in ("function", "script", "module", "method", "class", "entity")
                and s["role"] == "product"
            ]
            entry = sorted(
                (s for s in symbols if s["n_callers"] == 0 and s["n_callees"] > 0),
                key=lambda s: (-s["n_callees"], s["id"]),
            )[:25]
            if entry:
                lines += [
                    "### Entry points (no mapped caller, calls other project code)",
                    "",
                    "| Symbol | Kind | Calls | Where |",
                    "|---|---|---|---|",
                ]
                for s in entry:
                    label = s["name"] if s["qualname"] == "(file)" else s["qualname"]
                    lines.append(f"| `{label}` | {s['kind']} | {s['n_callees']} | `{s['cite']}` |")
                lines += [
                    "",
                    '"No mapped caller" means no resolved call site names it; it may still be invoked dynamically.',
                    "",
                ]
            hubs = sorted(
                (s for s in symbols if s["n_callers"] > 0), key=lambda s: (-s["n_callers"], s["id"])
            )[:25]
            if hubs:
                lines += ["### Most called", "", "| Symbol | Callers | Where |", "|---|---|---|"]
                for s in hubs:
                    label = s["name"] if s["qualname"] == "(file)" else s["qualname"]
                    lines.append(f"| `{label}` | {s['n_callers']} | `{s['cite']}` |")
                lines.append("")
    docs = cov.get("documents", {})
    if docs.get("n_documents"):
        lines += [
            "## Documents",
            "",
            f"{docs['n_documents']} documents with {docs.get('n_sections', 0)} sections and "
            f"{docs.get('n_words', 0)} words; {docs.get('n_references', 0)} references "
            f"({docs.get('n_references_external', 0)} external, {docs.get('n_references_unresolved', 0)} unresolved); "
            f"{docs.get('n_parameters', 0)} parameters (`cmx q param <label> --compare`). "
            "Outlines per document in `DOCMAP.md`; text cache under `text/`.",
            "",
        ]
        docs_path = ctx.layout.nodes / "documents.jsonl"
        if docs_path.is_file():
            from contextmax.io.jsonl import read_jsonl

            top_docs = sorted(read_jsonl(docs_path), key=lambda d: (-d["n_words"], d["file"]))[:30]
            lines += ["| Document | Format | Sections | Words | File |", "|---|---|---|---|---|"]
            for d in top_docs:
                lines.append(
                    f"| {d['title'][:70]} | {d['format']} | {d['n_sections']} | {d['n_words']} | `{d['file']}` |"
                )
            lines.append("")
    if cov["by_skip_reason"]:
        lines += ["## What was not fully indexed", "", "| Reason | Files |", "|---|---|"]
        for reason, count in sorted(cov["by_skip_reason"].items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| {reason} | {count} |")
        lines += ["", "Every entry is listed in `skipped.jsonl` with its reason.", ""]
    lines += [
        "## Files in this index",
        "",
        "- `nodes/files.jsonl` — one row per file: type, tier, role, size, hash.",
        "- `nodes/symbols.jsonl` — every function, class, script and region with signature, doc and span.",
        "- `edges/calls.jsonl` — call sites with resolution status, candidates and counts; `edges/imports.jsonl`, `edges/contains.jsonl`.",
        "- `CODEMAP.md` — the symbol tables per folder, with citations.",
        "- `nodes/documents.jsonl`, `nodes/sections.jsonl`, `nodes/references.jsonl` — documents, their outlines and their links, cross-references and citations.",
        "- `DOCMAP.md` — every document's outline and reference summary; `text/` holds the extracted text cache.",
        "- `skipped.jsonl` — every file not fully analysed and why.",
        "- `coverage.json` — counts by tier, language, format, role and reason.",
        "- `manifest.json` — provenance, identity hashes and the completeness verdict.",
        "- `build-state.json` — per-stage ledger of the last run.",
        "",
    ]
    text = "\n".join(lines)
    from contextmax.io.hash import sha256_bytes

    return sha256_bytes(atomic_write_text(ctx.layout.index_md, text))


def _write_index_readme(ctx: Context) -> None:
    text = (
        "# .contextmax\n\n"
        "Generated by ContextMAX. Everything here except `config.json` is derived data and can be\n"
        "rebuilt with `contextmax index`. Start with `INDEX.md`, then `manifest.json` for the\n"
        "completeness verdict, then `skipped.jsonl` before concluding that something is absent.\n"
    )
    atomic_write_text(ctx.layout.readme, text)


STAGE_TABLE: dict[str, Stage] = {
    "discover": Stage("discover", stage_discover),
    "code": Stage("code", stage_code),
    "documents": Stage("documents", stage_documents),
    "links": Stage("links", stage_links),
    "graph": Stage("graph", stage_graph),
    "catalogs": Stage("catalogs", stage_catalogs),
    "viz": Stage("viz", stage_viz),
    "skill": Stage("skill", stage_skill),
    "query": Stage("query", stage_query),
    "manifest": Stage("manifest", stage_manifest),
}

FEATURE_OF_STAGE = {
    "code": "code",
    "documents": "documents",
    "links": "links",
    "graph": "links",
    "viz": "viz",
    "skill": "skill",
}


def run_index(
    root: Path, *, options: dict[str, Any] | None = None, log: Callable[[str], None] = print
) -> int:
    """Run the pipeline. Returns the process exit code (0 clean, 1 with problems)."""
    options = dict(options or {})
    layout0 = layout_for(root, None)
    config = load_config(layout0.config)
    layout = layout_for(root, config.output_dir)
    layout.index.mkdir(parents=True, exist_ok=True)
    if not layout.skip_marker.exists():
        atomic_write_text(layout.skip_marker, "ContextMAX index folder: never indexed.\n")
    state = BuildState(layout.build_state)
    state.start(config.full_hash(), version.__version__, options)
    ctx = Context(root=root, config=config, layout=layout, options=options, state=state, log=log)

    for name in STAGES:
        stage = STAGE_TABLE.get(name)
        feature = FEATURE_OF_STAGE.get(name)
        enabled = True if feature is None else config.feature(feature)
        if stage is None:
            state.mark(
                name, implemented=False, enabled=enabled, note="not implemented in this version"
            )
            continue
        state.mark(name, implemented=True, enabled=enabled)
        if not enabled:
            state.mark(name, note="disabled by features")
            continue
        log(f"[{name}]")
        started = time.perf_counter()
        state.mark(name, attempted=True)
        try:
            stage.run(ctx)
        except Exception as exc:
            message = f"{name}: {exc.__class__.__name__}: {exc}"
            ctx.problems.append(message)
            state.mark(
                name, ok=False, error=message, seconds=round(time.perf_counter() - started, 3)
            )
            state.problem(message)
            log(f"  problem: {message}")
            continue
        state.mark(name, ok=True, seconds=round(time.perf_counter() - started, 3))
    state.finish()
    if ctx.problems:
        log(f"finished with {len(ctx.problems)} problem(s)")
        return 1
    log("finished")
    return 0


def marker_text() -> str:
    return f"{SKIP_MARKER}: ContextMAX never indexes this folder.\n"
