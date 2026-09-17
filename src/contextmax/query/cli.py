# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`cmx q <verb>`: the query commands. JSON when piped or asked; readable text on a terminal."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from contextmax.paths import NoIndexError
from contextmax.query.api import QueryError, open_index

VERBS = (
    "status",
    "search",
    "find",
    "symbol",
    "callers",
    "callees",
    "impact",
    "file",
    "deps",
    "doc",
    "docs",
    "outline",
    "section",
    "refs",
    "related",
    "explain",
    "skipped",
    "source",
    "param",
    "term",
)


def add_query_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "q",
        help="query the index (search, symbol, callers, impact, doc, outline, section, source, ...)",
    )
    p.add_argument("verb", choices=VERBS)
    p.add_argument("args", nargs="*", help="verb arguments (a name, an id, a path or a query)")
    p.add_argument("--root", help="project root (default: found from the current folder)")
    p.add_argument(
        "--json", action="store_true", help="always print JSON (default when not a terminal)"
    )
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--depth", default="1", help="hops for callers/callees: a number or 'all'")
    p.add_argument("--text", action="store_true", help="section: include the section text")
    p.add_argument(
        "--reverse", action="store_true", help="deps: show dependents instead of dependencies"
    )
    p.add_argument("--kind", action="append", help="search: restrict to a node kind (repeatable)")
    p.add_argument("--reason", help="skipped: filter by reason")
    p.add_argument("--context", type=int, default=0, help="source: extra lines around the range")
    p.add_argument("--compare", action="store_true", help="param: group by label and report agreement")
    p.add_argument("--value", type=float, help="param: only this numeric value")
    p.add_argument("--unit", help="param: only this unit (aliases normalised)")
    p.set_defaults(func=cmd_query)


def cmd_query(args: argparse.Namespace) -> int:
    try:
        index = open_index(args.root)
    except (NoIndexError, QueryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    depth: int | None
    depth = None if str(args.depth).lower() in ("all", "*", "0") else int(args.depth)
    a = args.args
    try:
        result = _dispatch(index, args.verb, a, args, depth)
    except QueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (IndexError, ValueError) as exc:
        print(f"error: {args.verb} needs an argument ({exc})", file=sys.stderr)
        return 2
    finally:
        index.con.close()
    if args.json or not sys.stdout.isatty():
        sys.stdout.write(json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    else:
        _render(args.verb, result)
    return 0


def _dispatch(index, verb: str, a: list[str], args, depth) -> Any:
    if verb == "status":
        return index.status()
    if verb == "search":
        return index.search(" ".join(a), tuple(args.kind) if args.kind else None, args.limit)
    if verb == "find":
        return index.find_symbol(a[0], args.limit)
    if verb == "symbol":
        return index.symbol(a[0])
    if verb == "callers":
        return index.callers(a[0], depth)
    if verb == "callees":
        return index.callees(a[0], depth)
    if verb == "impact":
        return index.impact(a[0])
    if verb == "file":
        return index.file(a[0])
    if verb == "deps":
        return index.deps(a[0], reverse=args.reverse)
    if verb == "docs":
        return index.find_document(" ".join(a) if a else "", args.limit)
    if verb == "doc":
        return index.document(a[0])
    if verb == "outline":
        return index.outline(a[0])
    if verb == "section":
        return index.section(a[0], with_text=args.text)
    if verb == "refs":
        return index.references(a[0])
    if verb == "related":
        return index.related(a[0])
    if verb == "explain":
        return index.explain(a[0], a[1])
    if verb == "skipped":
        return index.skipped(args.reason or (a[0] if a else None), args.limit)
    if verb == "source":
        return index.source(a[0], context=args.context)
    if verb == "param":
        return index.parameter(" ".join(a), compare=args.compare, value=args.value, unit=args.unit, limit=args.limit)
    if verb == "term":
        return index.term(" ".join(a), args.limit)
    raise QueryError(f"unknown verb {verb}")


def _render(verb: str, result: Any) -> None:
    w = sys.stdout.write
    if verb == "term":
        w(f"{result['n']} term(s) for '{result['query']}'\n")
        for hit in result["hits"]:
            head = hit["name"] + (f" ({hit['acronym']})" if hit.get("acronym") and hit["acronym"] != hit["name"] else "")
            if hit.get("expansion") and hit["expansion"] != hit["name"]:
                head += f" = {hit['expansion']}"
            w(f"  {head}  [{', '.join(hit['methods'] or [])}]  in {hit['n_documents']} document(s), {hit['n_occurrences']} occurrence(s)\n")
            if hit.get("definition"):
                w(f"      definition: {hit['definition']}\n")
            for d in hit["defined_in"][:3]:
                w(f"      defined at {d['cite']}\n")
            for o in hit["top_occurrences"][:3]:
                w(f"      {o['count']}x at {o['cite']}\n")
        w(f"{result['note']}\n")
        return
    if verb == "param":
        w(f"{result['n']} parameter(s) for '{result['query']}'\n")
        for hit in result["hits"]:
            unit = f" {hit['unit_norm'] or hit['unit']}" if (hit.get("unit_norm") or hit.get("unit")) else ""
            formula = f"  {hit['formula']}" if hit.get("formula") else ""
            hidden = "  (hidden)" if hit.get("hidden") else ""
            w(f"  {hit['label']} = {hit['display']}{unit}{formula}{hidden}  [{hit['source_kind']}]  {hit['cite']}\n")
        for group in result.get("comparison", []):
            w(
                f"  {group['label_norm']}: {group['verdict']} across {group['n_documents']} document(s), "
                f"values {', '.join(group['distinct_values'])}\n"
            )
        w(f"{result['note']}\n")
        return
    if verb == "status":
        comp = result.get("completeness") or {}
        w(f"{result['project']['name']} ({result['project']['slug']})  index {result['index']}\n")
        w(
            f"built {result.get('generated_utc')}  completeness={comp.get('verdict')}  engine {result.get('engine_version')}\n"
        )
        cov = result.get("coverage") or {}
        w(f"files {cov.get('n_files')}  tiers {cov.get('by_tier')}  skips {cov.get('n_skipped')}\n")
        for area in ("code", "documents", "links"):
            if cov.get(area):
                w(
                    f"{area}: "
                    + ", ".join(f"{k}={v}" for k, v in cov[area].items() if not isinstance(v, dict))
                    + "\n"
                )
        return
    if verb == "search":
        w(f"{result['n']} hits for '{result['query']}' ({result['engine']})\n")
        for h in result["hits"]:
            w(
                f"  [{h['kind']}] {h['name']}  ({h['cite']})\n      {h['snippet'].replace(chr(10), ' ')[:140]}\n"
            )
        return
    if verb == "find":
        for s in result["symbols"]:
            w(f"  {s['kind']:10} {s['qualname']:40} {s['cite']}  tier {s['tier']}\n")
        return
    if verb == "symbol":
        s = result["symbol"]
        w(
            f"{s['kind']} {s.get('qualname')}  ({s['cite']})  tier {s['tier']} confidence {s.get('confidence')} role {s['role']}\n"
        )
        if s.get("signature"):
            w(f"  {s['signature']}\n")
        if s.get("doc"):
            w(f"  doc: {s['doc']}\n")
        for label in ("callers", "callees"):
            w(f"  {label} ({len(result[label])}):\n")
            for n in result[label]:
                w(f"    {n['qualname']:40} {n['cite']}  x{n['count']} {n['evidence']}\n")
        if result["possible_callers"]:
            w(
                f"  possible callers (unresolved or ambiguous sites naming it): {len(result['possible_callers'])}\n"
            )
            for n in result["possible_callers"][:10]:
                w(f"    {n['qualname']:40} {n['cite']}  {n['status']}\n")
        if result["documents"]:
            w(f"  mentioned in documents ({len(result['documents'])}):\n")
            for d in result["documents"]:
                w(f"    {d['title'][:50]:50} {d['cite']}  {d['confidence']}\n")
        return
    if verb in ("callers", "callees"):
        w(
            f"{result['direction']} of {result['symbol']} (depth {result['depth'] or 'all'}): {result['n_direct']} direct, {result['n_total']} total, by role {result['by_role']}\n"
        )
        for n in result["nodes"]:
            w(f"  {'  ' * (n['hops'] - 1)}{n['qualname']:40} {n['cite']}\n")
        return
    if verb == "impact":
        s = result["symbol"]
        w(f"impact of {s['qualname']} ({s['cite']})\n")
        w(
            f"  upstream:   {result['upstream']['n_direct']} direct, {result['upstream']['n_total']} total {result['upstream']['by_role']}\n"
        )
        w(
            f"  downstream: {result['downstream']['n_direct']} direct, {result['downstream']['n_total']} total {result['downstream']['by_role']}\n"
        )
        for n in result["upstream_nodes"][:30]:
            w(f"    <- {n['qualname']:40} {n['cite']}  ({n['hops']} hop)\n")
        if result["possible_callers"]:
            w(f"  possible callers: {len(result['possible_callers'])}\n")
        if result["documents"]:
            w(f"  documents: {len(result['documents'])}\n")
            for d in result["documents"][:10]:
                w(f"    {d['title'][:50]:50} {d['cite']}\n")
        w(f"  note: {result['note']}\n")
        return
    if verb == "file":
        f = result["file"]
        w(
            f"{f['file']}  {f['content_family']} {f.get('language') or f.get('format')}  tier {f['tier']}  role {f['role']}  {f['size']} bytes  {f.get('lines')} lines\n"
        )
        if result["document"]:
            w(
                f"  document: {result['document']['title']}  {result['document']['n_sections']} sections, {result['document']['n_words']} words\n"
            )
        w(f"  symbols ({len(result['symbols'])}):\n")
        for s in result["symbols"][:60]:
            w(f"    {s['kind']:10} {s['qualname']:40} {s['cite']}\n")
        for label in ("depends_on", "depended_on_by"):
            if result[label]:
                w(
                    f"  {label} ({len(result[label])}): "
                    + ", ".join(d["file"] for d in result[label][:12])
                    + "\n"
                )
        return
    if verb == "deps":
        w(f"{result['direction']} of {result['file']}: {result['n']}\n")
        for d in result["files"]:
            w(f"  {d['file']}  ({d['evidence']})\n")
        return
    if verb == "docs":
        for d in result["documents"]:
            w(
                f"  {d['title'][:50]:50} {d['file']}  {d['format']} {d['n_sections']} sections {d['n_words']} words\n"
            )
        return
    if verb == "doc":
        d = result["document"]
        w(
            f"{d['title']}  ({d['file']})  {d['format']} via {d['adapter']} [{d['determinism']}]  {d['n_words']} words\n"
        )
        for s in result["outline"]:
            w(
                f"  {'  ' * (s['depth'] - 1)}{(s['number'] + ' ') if s['number'] else ''}{s['title']}  ({s['cite']})\n"
            )
        w(f"  references: {result['references_summary']}\n")
        if result["symbols_mentioned"]:
            w(f"  symbols mentioned: {', '.join(result['symbols_mentioned'][:15])}\n")
        return
    if verb == "outline":
        w(f"{result['title']}  {result['n_sections']} sections\n")
        for s in result["sections"]:
            w(
                f"  {'  ' * (s['depth'] - 1)}{(s['number'] + ' ') if s['number'] else ''}{s['title']}  ({s['cite']})\n"
            )
        return
    if verb == "section":
        s = result["section"]
        w(f"{s.get('title') or s.get('name')}  ({s['cite']})\n")
        if "text" in result:
            w(result["text"] + ("\n" if not result["text"].endswith("\n") else ""))
        return
    if verb == "refs":
        for r in result["references"]:
            state = "resolved" if r["resolved"] else ("external" if r["external"] else "unresolved")
            w(
                f"  {r['ref_kind']:9} {state:10} {r['raw'][:50]:50} -> {r['resolved'] or ''}  ({r['cite']})\n"
            )
        return
    if verb == "related":
        w(f"{result['node']['id']}  ({result['node']['cite']})\n")
        for rel, rows in result["relations"].items():
            w(f"  {rel} ({len(rows)}):\n")
            for r in rows[:20]:
                w(
                    f"    {str(r['name'])[:45]:45} {r.get('cite') or ''}  {r.get('status')}/{r.get('confidence')}\n"
                )
        return
    if verb == "explain":
        w(f"{result['n']} edge(s) between {result['src']} and {result['dst']}\n")
        for e in result["edges"]:
            w(
                f"  {e['src']} -[{e['rel']} {e['status']} {e.get('confidence')}]-> {e['dst']}  {e.get('evidence')}\n"
            )
        return
    if verb == "skipped":
        w(f"{result['n']} skipped: {result['by_reason']}\n")
        for r in result["rows"][:50]:
            w(f"  {r['reason_code']:22} {r['file']}\n")
        return
    if verb == "source":
        w(f"{result['cite']}\n")
        for line in result["lines"]:
            w(f"{line['n']:5}  {line['text']}\n")
        return
    sys.stdout.write(json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
