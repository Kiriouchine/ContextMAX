# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`cmx skill render|install|hosts` and `cmx viz`."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser

from contextmax.config import ConfigError, load_config
from contextmax.paths import NoIndexError, layout_for, resolve_root
from contextmax.skill.render import SkillError, install, list_hosts, write_rendered


def add_skill_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("skill", help="render the project's skill and install it into an AI host")
    p.add_argument("action", choices=["render", "install", "hosts"])
    p.add_argument("--root", help="project root (default: found from the current folder)")
    p.add_argument("--host", action="append", help="host id (repeatable); see `skill hosts`")
    p.add_argument("--path", help="destination for the 'custom' host")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_skill)

    v = sub.add_parser("viz", help="open (or print the path of) the offline HTML views")
    v.add_argument("page", nargs="?", default="index", choices=["index", "code", "docs"])
    v.add_argument("--root")
    v.add_argument(
        "--no-open", action="store_true", help="print the path instead of opening a browser"
    )
    v.set_defaults(func=cmd_viz)


def _project(root_arg):
    root = resolve_root(root_arg)
    layout0 = layout_for(root, None)
    config = load_config(layout0.config)
    return config, layout_for(root, config.output_dir)


def cmd_skill(args: argparse.Namespace) -> int:
    if args.action == "hosts":
        rows = list_hosts()
        if args.json:
            print(json.dumps(rows, indent=1))
        else:
            for r in rows:
                print(f"  {r['id']:22} {r['layout']:12} {r['path'] or '(--path)'}")
                print(f"  {'':22} {r['label']}")
        return 0
    try:
        config, layout = _project(args.root)
    except (NoIndexError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    try:
        if args.action == "render":
            target = write_rendered(config, layout, None)
            print(f"rendered {target}")
            return 0
        hosts_wanted = (
            args.host or config.data.get("skill", {}).get("hosts") or ["claude-code-project"]
        )
        for host in hosts_wanted:
            dest = install(config, layout, host, args.path)
            print(f"installed {host}: {dest}")
        return 0
    except SkillError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def cmd_viz(args: argparse.Namespace) -> int:
    try:
        _config, layout = _project(args.root)
    except (NoIndexError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    page = layout.viz_dir / f"{args.page}.html"
    if not page.is_file():
        print(f"error: {page} not found; run `contextmax index`", file=sys.stderr)
        return 1
    print(page)
    if not args.no_open:
        webbrowser.open(page.as_uri())
    return 0
