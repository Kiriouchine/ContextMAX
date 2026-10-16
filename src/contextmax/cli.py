"""contextmax / cmx: create a project, choose its folders, build it, open it, ask it.

    contextmax new "Demo project" --folder C:\\work\\src=code --folder C:\\work\\docs=documents
    contextmax folders demo-project --add D:\\specs --holds documents
    contextmax build demo-project              # quick: code, document map, pages
    contextmax build demo-project --documents  # also reads new and changed documents
    contextmax build demo-project --full       # everything, failed documents retried
    contextmax open demo-project
    contextmax find demo-project symbol pid_step
    contextmax params demo-project --name "settle time" --compare
    contextmax sheet demo-project --key Error_budget --trace Budget!B7
    contextmax skill install demo-project
    contextmax panel                          # the window with folder picker and buttons
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from contextmax import VERSION, project


def _project_ref(p: str):
    return project.lookup(p)


def cmd_new(a) -> int:
    folders = []
    for spec in a.folder or []:
        path, holds = spec, "both"
        if "=" in spec and spec.rsplit("=", 1)[1] in project.HOLDS:
            path, holds = spec.rsplit("=", 1)
        folders.append({"path": path, "holds": holds})
    proj = project.create(a.name, folders, a.workspace)
    print(f"project {proj.slug} created in {proj.workspace}")
    for f in proj.folders:
        print(f"  {f.name}: {f.path} ({f.holds})")
    print(f"next: contextmax build {proj.slug} --documents")
    return 0


def cmd_list(a) -> int:
    reg = project.list_projects()
    if not reg:
        print("no projects yet: contextmax new \"My project\" --folder C:\\path")
    for slug, ws in reg.items():
        print(f"{slug:<28} {ws}")
    return 0


def cmd_folders(a) -> int:
    proj = _project_ref(a.project)
    if a.add:
        f = project.add_folder(proj, a.add, a.name, a.holds)
        print(f"added {f.name}: {f.path} ({f.holds})")
    if a.remove:
        print("removed" if project.remove_folder(proj, a.remove) else f"no folder called {a.remove}")
    for f in proj.folders:
        print(f"  {f.name:<24} {f.holds:<10} {f.path}")
    if (a.add or a.remove) and proj.folders:
        # links run across folders: a new or removed folder changes them anywhere in the project
        print(f"build again so every link takes the change into account: contextmax build {proj.slug} --documents")
    return 0


def cmd_build(a) -> int:
    from contextmax import pipeline

    proj = _project_ref(a.project)
    depth = "full" if a.full else "documents" if a.documents else "catalogue" if a.catalogue else "quick"
    try:
        report = pipeline.build(proj, depth=depth, ocr=not a.no_ocr)
    except pipeline.GateFailed:
        return 1
    m = report.get("manifest") or {}
    print(f"\nconfidence {m.get('confidence', '?')} \u00b7 index {str(m.get('outputs_hash', ''))[:12]}"
          f" \u00b7 open: {proj.workspace / 'Home.html'}")
    return 0


def cmd_open(a) -> int:
    proj = _project_ref(a.project)
    page = proj.workspace / "Home.html"
    if not page.exists():
        print(f"not built yet: contextmax build {proj.slug}")
        return 3
    os.startfile(str(page)) if sys.platform == "win32" else print(page)  # type: ignore[attr-defined]
    return 0


def cmd_validate(a) -> int:
    from contextmax.docs import corpus

    proj = _project_ref(a.project)
    errors, counts = corpus.validate(proj)
    for e in errors[:50]:
        print("  -", e)
    print(("FAILED: " if errors else "OK: ") + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return 1 if errors else 0


def cmd_status(a) -> int:
    from contextmax import query

    proj = _project_ref(a.project)
    s = query.status(proj)
    if a.json:
        print(json.dumps(s, indent=2, ensure_ascii=False))
    else:
        print(query.status_line(proj, s))
        for k in ("built", "sync", "problems"):
            if s.get(k):
                print(f"  {k}: {s[k]}")
    return 0


def cmd_find(a) -> int:
    from contextmax import query

    proj = _project_ref(a.project)
    out = query.find(proj, a.what, a.query, target=a.target, depth=a.depth, limit=a.limit)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0 if out.get("hits") or out.get("ok") else 3


def cmd_params(a) -> int:
    from contextmax import query

    proj = _project_ref(a.project)
    out = query.params(proj, name=a.name, compare=a.compare, value=a.value, exact=a.exact, unit=a.unit,
                       origin=a.origin, named_only=a.named, limit=a.limit)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


def cmd_sheet(a) -> int:
    from contextmax import query

    proj = _project_ref(a.project)
    return query.sheet(proj, key=a.key, path=a.path, sheet=a.sheet, cell=a.cell, trace=a.trace, lint=a.lint)


def cmd_skill(a) -> int:
    from contextmax import agentskill, assistants

    proj = _project_ref(a.project)
    for line in agentskill.install(proj, a.host) + assistants.prepare(proj):
        print(line)
    return 0


def cmd_checkup(a) -> int:
    from contextmax import checkup

    return checkup.run(json_out=a.json)


def cmd_share(a) -> int:
    from contextmax import share

    return share.share(_project_ref(a.project), a.dest, dry_run=a.dry_run, yes=a.yes)


def cmd_selfcheck(a) -> int:
    from contextmax import share

    return share.selfcheck(_project_ref(a.project))


def cmd_demo(a) -> int:
    from contextmax import demo, pipeline

    dest = a.folder or str(project.default_home() / "demo-source")
    proj = demo.create_project(dest, a.workspace)
    print(f"demo written to {dest}; project {proj.slug} in {proj.workspace}")
    pipeline.build(proj, depth="documents", ocr=False)
    print(f"open: {proj.workspace / 'Home.html'}")
    return 0


def cmd_panel(a) -> int:
    from contextmax import panel

    return panel.serve(a.project, port=a.port, open_browser=not a.no_browser)


def _shell_places(a) -> dict:
    """Where install and uninstall put things; the hidden options let the tests use other places."""
    from contextmax import install

    return {"start_menu": Path(a.start_menu) if a.start_menu else None,
            "desktop": Path(a.desktop) if a.desktop else None,
            "env_key": a.env_key or install.ENV_KEY, "uninstall_key": a.uninstall_key or install.UNINSTALL_KEY,
            "link_key": a.link_key or install.LINK_KEY}


def cmd_install(a) -> int:
    from contextmax import install

    for line in install.install(shortcuts=not a.no_shortcuts, path=not a.no_path, apps_entry=not a.no_apps_entry,
                                links=not a.no_links, **_shell_places(a)):
        print("  " + line)
    return 0


def cmd_uninstall(a) -> int:
    from contextmax import install

    for line in install.uninstall(**_shell_places(a)):
        print("  " + line)
    return 0


def cmd_link(a) -> int:
    from contextmax import opener

    return opener.handle_link(a.url)


def cmd_ocr_models(a) -> int:
    from contextmax.docs import ocr

    try:
        for line in ocr.fetch_models(source=Path(a.source) if a.source else None):
            print("  RapidOCR " + line)
    except OSError as exc:
        print(f"  RapidOCR: {exc}. Scans in Latin script are still read; run setup.cmd again with internet "
              "for Cyrillic.", file=sys.stderr)
        return 1
    return 0


def cmd_offline_installer(a) -> int:
    from contextmax import bundle

    source = Path(a.source)
    try:
        target = bundle.make(source, Path(a.out) if a.out else source / "dist")
    except bundle.BundleError as exc:
        print(f"no offline installer was made: {exc}", file=sys.stderr)
        return 1
    print(f"\nOffline installer: {target} ({target.stat().st_size / 1e6:.0f} MB)\n"
          "Copy it to the PC without internet, unzip it there and double-click setup.cmd.")
    return 0


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="contextmax", description="Maps of a project's code and documents, and the links between them.")
    ap.add_argument("--version", action="version", version=f"ContextMAX {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="create a project from one or more folders")
    p.add_argument("name")
    p.add_argument("--folder", action="append", help="PATH or PATH=code|documents|both (repeatable)")
    p.add_argument("--workspace", help="where the index lives (default: %%USERPROFILE%%\\ContextMAX\\<project>)")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("list", help="the projects on this PC")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("folders", help="show, add or remove a project's folders")
    p.add_argument("project")
    p.add_argument("--add")
    p.add_argument("--name")
    p.add_argument("--holds", default="both", choices=project.HOLDS)
    p.add_argument("--remove")
    p.set_defaults(fn=cmd_folders)

    p = sub.add_parser("build", help="build or refresh a project's index and pages")
    p.add_argument("project")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--catalogue", action="store_true", help="the file catalogue only")
    g.add_argument("--documents", action="store_true", help="also read new and changed documents")
    g.add_argument("--full", action="store_true", help="everything, retrying documents that failed before")
    p.add_argument("--no-ocr", action="store_true", help="skip text recognition of scanned PDFs")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("open", help="open the project's home page")
    p.add_argument("project")
    p.set_defaults(fn=cmd_open)

    p = sub.add_parser("status", help="how fresh and complete the index is")
    p.add_argument("project")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("validate", help="run the document map's strict checks")
    p.add_argument("project")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("find", help="look something up (JSON out)")
    p.add_argument("project")
    p.add_argument("what", choices=["doc", "symbol", "callers", "callees", "impact", "module", "docs-for", "code-for", "links"])
    p.add_argument("query")
    p.add_argument("--target", help="code base name (default: all)")
    p.add_argument("--depth", type=int, default=0, help="impact/callers: levels to follow (0 = all)")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=cmd_find)

    p = sub.add_parser("params", help="named values: where stated, and whether the documents agree")
    p.add_argument("project")
    p.add_argument("--name", help="the value's name (main lookup)")
    p.add_argument("--compare", action="store_true", help="one row per document with an agreement verdict")
    p.add_argument("--value", help="a number (rounded match)")
    p.add_argument("--exact", help="a number (exact match on the raw cell)")
    p.add_argument("--unit")
    p.add_argument("--origin", choices=["cell_entry", "computed_value", "formula_constant", "prose_value"])
    p.add_argument("--named", action="store_true", help="only values that have a name")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_params)

    p = sub.add_parser("sheet", help="read one workbook live: cells, formulas, a trace, a row-pairing check")
    p.add_argument("project")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--key", help="the document's key from the index")
    g.add_argument("--path", help="a path to the workbook")
    p.add_argument("--sheet")
    p.add_argument("--cell")
    p.add_argument("--trace", help="SHEET!CELL: where does this number come from")
    p.add_argument("--lint", action="store_true", help="find label and value cells that point at different rows")
    p.set_defaults(fn=cmd_sheet)

    p = sub.add_parser("skill", help="install the AI skill for this project")
    p.add_argument("action", choices=["install"])
    p.add_argument("project")
    p.add_argument("--host", default="all", choices=["claude", "copilot", "codex", "all"])
    p.set_defaults(fn=cmd_skill)

    p = sub.add_parser("checkup", help="what this PC can read")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_checkup)

    p = sub.add_parser("share", help="write a portable copy for colleagues into a shared folder")
    p.add_argument("project")
    p.add_argument("dest", help="the shared folder")
    p.add_argument("--dry-run", action="store_true", help="list what would be written, write nothing")
    p.add_argument("--yes", action="store_true", help="do not ask to type SHARE")
    p.set_defaults(fn=cmd_share)

    p = sub.add_parser("selfcheck", help="a verdict and a JSON file to send to whoever helps")
    p.add_argument("project")
    p.set_defaults(fn=cmd_selfcheck)

    p = sub.add_parser("demo", help="write a small made-up project and build it, to try every view")
    p.add_argument("folder", nargs="?", help="where to write the demo's files")
    p.add_argument("--workspace")
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("panel", help="open the ContextMAX window: choose folders, build, browse")
    p.add_argument("project", nargs="?")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_panel)

    for name, fn, text in (("install", cmd_install, "set ContextMAX up as a program for this user (setup.cmd runs it)"),
                           ("uninstall", cmd_uninstall, "remove its shortcuts, PATH entry and Apps entry (uninstall.cmd runs it)")):
        p = sub.add_parser(name, help=text)
        if name == "install":
            p.add_argument("--no-shortcuts", action="store_true", help="no Start menu and desktop shortcuts")
            p.add_argument("--no-path", action="store_true", help="do not put the contextmax command on the PATH")
            p.add_argument("--no-apps-entry", action="store_true", help="no entry in Apps & features")
            p.add_argument("--no-links", action="store_true",
                           help="no contextmax-open: links (Open document on pages opened from the folder)")
        for hidden in ("--start-menu", "--desktop", "--env-key", "--uninstall-key", "--link-key"):
            p.add_argument(hidden, help=argparse.SUPPRESS)
        p.set_defaults(fn=fn)

    p = sub.add_parser("link", help=argparse.SUPPRESS)        # what a contextmax-open: link runs
    p.add_argument("url")
    p.set_defaults(fn=cmd_link)

    p = sub.add_parser("ocr-models", help="fetch RapidOCR's Cyrillic model, checked by SHA-256 (setup.cmd runs it)")
    p.add_argument("--from", dest="source", help="copy it from this folder instead (an offline installer's wheels\\models)")
    p.set_defaults(fn=cmd_ocr_models)

    p = sub.add_parser("offline-installer", help="make a zip that installs ContextMAX on a PC without internet "
                                                 "(make-offline-installer.cmd runs it)")
    p.add_argument("--source", required=True, help="the ContextMAX folder with setup.cmd")
    p.add_argument("--out", help="where the zip goes (default: <source>\\dist)")
    p.set_defaults(fn=cmd_offline_installer)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")          # the Windows console otherwise mangles · and →
        except (AttributeError, ValueError):
            pass
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
