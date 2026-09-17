# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""The `contextmax` / `cmx` command line."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

from contextmax import version
from contextmax.buildstate import BuildState
from contextmax.config import (
    GITIGNORE_BLOCK,
    ConfigError,
    default_config,
    load_config,
    slugify,
    write_config,
)
from contextmax.io.atomic import atomic_write_text
from contextmax.io.jsonl import read_json
from contextmax.paths import INDEX_DIR_NAME, NoIndexError, layout_for, resolve_root


def _out(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def _table(rows: list[list[str]], header: list[str]) -> str:
    widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    lines = [fmt.format(*header), fmt.format(*["-" * w for w in widths])]
    lines += [fmt.format(*row) for row in rows]
    return "\n".join(lines)


# --- init -----------------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path or ".").resolve()
    if not root.is_dir():
        print(f"error: {root} is not a folder", file=sys.stderr)
        return 2
    index_dir = root / INDEX_DIR_NAME
    config_path = index_dir / "config.json"
    if config_path.exists() and not args.force:
        print(f"already initialised: {config_path} (use --force to overwrite)")
        return 0
    slug = args.slug or slugify(root.name)
    data = default_config(slug, args.name or root.name, args.description or "")
    index_dir.mkdir(parents=True, exist_ok=True)
    write_config(config_path, data)
    atomic_write_text(index_dir / ".contextmax-skip", "ContextMAX index folder: never indexed.\n")
    print(f"created {config_path}")
    if not args.no_gitignore and (root / ".git").exists():
        gi = root / ".gitignore"
        existing = gi.read_text(encoding="utf-8-sig") if gi.is_file() else ""
        if ".contextmax/*" not in existing:
            sep = "" if not existing or existing.endswith("\n") else "\n"
            atomic_write_text(gi, existing + sep + ("\n" if existing else "") + GITIGNORE_BLOCK)
            print(f"updated {gi} to ignore the generated index (config.json stays versioned)")
    print("next: `contextmax index`")
    return 0


# --- index ----------------------------------------------------------------------------------


def cmd_index(args: argparse.Namespace) -> int:
    from contextmax.pipeline import run_index

    try:
        root = resolve_root(args.root)
    except NoIndexError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    log = (lambda _msg: None) if args.quiet else print
    try:
        return run_index(root, options={"full": bool(args.full)}, log=log)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


# --- status ---------------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    try:
        root = resolve_root(args.root)
    except NoIndexError as exc:
        if args.json:
            _out({"found": False, "error": str(exc)})
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 3
    layout0 = layout_for(root, None)
    try:
        config = load_config(layout0.config)
    except ConfigError as exc:
        if args.json:
            _out({"found": True, "root": str(root), "config_valid": False, "errors": exc.messages})
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    layout = layout_for(root, config.output_dir)
    manifest = read_json(layout.manifest) if layout.manifest.is_file() else None
    coverage = read_json(layout.coverage) if layout.coverage.is_file() else None
    state = BuildState.load(layout.build_state)
    payload = {
        "found": True,
        "root": str(root),
        "index": str(layout.index),
        "project": {"slug": config.slug, "name": config.name},
        "config_valid": True,
        "built": manifest is not None,
        "engine_version": version.__version__,
        "manifest": {
            "generated_utc": manifest.get("generated_utc"),
            "baseline_identity_hash": manifest.get("baseline_identity_hash"),
            "artifact_identity_hash": manifest.get("artifact_identity_hash"),
            "completeness": manifest.get("completeness"),
        }
        if manifest
        else None,
        "coverage": {
            "n_files": coverage.get("n_files"),
            "by_tier": coverage.get("by_tier"),
            "n_skipped": coverage.get("n_skipped"),
            "by_skip_reason": coverage.get("by_skip_reason"),
        }
        if coverage
        else None,
        "last_build": {
            "started_utc": state.get("started_utc"),
            "finished_utc": state.get("finished_utc"),
            "problems": state.get("problems", []),
        }
        if state
        else None,
    }
    if args.json:
        _out(payload)
        return 0
    print(f"project   {config.name} ({config.slug})")
    print(f"root      {root}")
    print(f"index     {layout.index}")
    if manifest is None:
        print("built     no (run `contextmax index`)")
        return 0
    comp = manifest["completeness"]
    print(f"built     {manifest['generated_utc']}  completeness={comp['verdict']}")
    print(f"baseline  {manifest['baseline_identity_hash']}")
    print(f"artifact  {manifest['artifact_identity_hash']}")
    if coverage:
        tiers = coverage["by_tier"]
        print(
            f"files     {coverage['n_files']}  tiers A={tiers['A']} B={tiers['B']} C={tiers['C']} D={tiers['D']}"
        )
        if coverage["by_skip_reason"]:
            reasons = ", ".join(f"{k}={v}" for k, v in sorted(coverage["by_skip_reason"].items()))
            print(f"skips     {coverage['n_skipped']}  ({reasons})")
    if state and state.get("problems"):
        print("problems  " + "; ".join(state["problems"]))
    return 0


# --- doctor ---------------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    from contextmax.doctor import checks_to_dict, run_doctor

    checks, code = run_doctor(args.root)
    if args.json:
        _out(checks_to_dict(checks, code))
        return code
    rows = [[c.area, c.name, c.state.upper(), c.detail] for c in checks]
    print(_table(rows, ["area", "check", "state", "detail"]))
    return code


# --- parser ---------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contextmax",
        description="Deterministic, offline indexing, graphing and linking of code and documents.",
    )
    parser.add_argument("--version", action="version", version=f"contextmax {version.__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create .contextmax/config.json for a project")
    p.add_argument("path", nargs="?", help="project folder (default: current)")
    p.add_argument("--slug", help="short lowercase identifier (default: from folder name)")
    p.add_argument("--name", help="display name")
    p.add_argument("--description", help="one sentence used in the generated skill")
    p.add_argument("--force", action="store_true", help="overwrite an existing config")
    p.add_argument(
        "--no-gitignore",
        action="store_true",
        help="do not add the ignore block to .gitignore (only done when the folder is a git repo)",
    )
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("index", help="build (or rebuild) the index")
    p.add_argument("--root", help="project root (default: found from the current folder)")
    p.add_argument("--full", action="store_true", help="ignore caches and rebuild everything")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("status", help="show what is built, how complete it is and what was skipped")
    p.add_argument("--root")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("doctor", help="check the environment, readers, grammars and index")
    p.add_argument("--root")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    # File names and document titles are arbitrary Unicode; never let a legacy console
    # code page turn them into a crash.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
