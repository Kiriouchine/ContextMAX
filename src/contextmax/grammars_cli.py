# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`cmx grammars fetch|status|list`: the only place ContextMAX ever downloads anything."""

from __future__ import annotations

import argparse
import json
import sys

from contextmax import grammars


def add_grammars_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("grammars", help="provision tree-sitter grammars for tier B (network, once)")
    p.add_argument("action", choices=["fetch", "status", "list"])
    p.add_argument("names", nargs="*", help="grammar names for fetch (e.g. python matlab c)")
    p.add_argument("--all", action="store_true", help="fetch every grammar in the pack (large)")
    p.add_argument(
        "--for-project",
        action="store_true",
        help="fetch the grammars of the languages in the current index",
    )
    p.add_argument("--root", help="project root for --for-project")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_grammars)


def _project_grammars(root_arg: str | None) -> list[str]:
    from contextmax.config import load_config
    from contextmax.io.jsonl import iter_jsonl
    from contextmax.paths import layout_for, resolve_root

    root = resolve_root(root_arg)
    config = load_config(layout_for(root, None).config)
    layout = layout_for(root, config.output_dir)
    if not layout.files_jsonl.is_file():
        raise RuntimeError(
            "no index yet; run `contextmax index` first, or name the grammars explicitly"
        )
    names = {row["grammar"] for row in iter_jsonl(layout.files_jsonl) if row.get("grammar")}
    return sorted(names)


def cmd_grammars(args: argparse.Namespace) -> int:
    if args.action == "status":
        st = grammars.status()
        if args.json:
            print(json.dumps(st, indent=1, sort_keys=True))
        else:
            print(f"pack installed: {st['pack_installed']} (version {st['pack_version']})")
            print(f"folder:         {st['folder']}")
            print(f"bundle present: {st['bundle_present']}")
            print(f"provisioned:    {st['n_provisioned']} grammar(s)")
            if st["with_tags"]:
                print("  tier B ready: " + ", ".join(st["with_tags"]))
            if st["without_tags"]:
                print(
                    "  no tags query (stay tier C until a plugin exists): "
                    + ", ".join(st["without_tags"])
                )
        return 0
    if args.action == "list":
        names = grammars.manifest_languages()
        if args.json:
            print(json.dumps(names))
        else:
            print(f"{len(names)} grammars in the pack manifest" if names else "pack not installed")
            print(", ".join(names))
        return 0
    try:
        if args.all:
            result = grammars.fetch(all_languages=True)
        else:
            names = list(args.names)
            if args.for_project:
                names += _project_grammars(args.root)
            if not names:
                print("error: name grammars, or use --for-project or --all", file=sys.stderr)
                return 2
            result = grammars.fetch(sorted(set(names)))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
    else:
        print(
            f"provisioned {len(result['provisioned'])} grammar(s) into {result['folder']} (pack {result['pack_version']})"
        )
        if result["provisioned"]:
            print("  " + ", ".join(result["provisioned"]))
        if result["failed"]:
            print("failed: " + ", ".join(f"{k} ({v})" for k, v in result["failed"].items()))
        if result["unknown"]:
            print("unknown to the pack: " + ", ".join(result["unknown"]))
    return 0 if not result["failed"] else 1
