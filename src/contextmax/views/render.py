"""Write the pages into <workspace>/pages/: one per code base, the documents, the Complete Atlas, the parameters,
the connections.

Each page is a single HTML file with its data inline and three shared files beside it
(cmx.css, cmx.js, vis-network.min.js). Nothing is fetched from the network, so the pages
open from the folder, offline, and look the same on every machine. No page holds a
timestamp, so the same index always writes the same bytes.
"""
from __future__ import annotations

import shutil
from html import escape
from pathlib import Path

from contextmax import parallel, util
from contextmax.views import atlas_data, code_data, docs_data, params_data

ASSETS = Path(__file__).resolve().parent / "assets"
SHARED = ["cmx.css", "cmx.js", "code.js", "documents.js", "atlas.js", "params.js", "connections.js", "vis-network.min.js"]


def _nav(proj, active: str, targets: list[dict]) -> str:
    links = ['<a href="../Home.html">Home</a>']
    if (proj.documents_dir / "doc-list.jsonl").exists() or targets:
        on = ' class="is-on"' if active == "atlas" else ""
        links.append(f'<a{on} href="atlas.html">Complete Atlas</a>')
    for t in targets:
        on = ' class="is-on"' if active == f"code-{t['name']}" else ""
        label = "Code" if len(targets) == 1 else f"Code: {escape(t['label'])}"
        links.append(f'<a{on} href="code-{escape(t["name"])}.html">{label}</a>')
    for page, label in (("documents", "Documents"), ("params", "Parameters"), ("connections", "Connections")):
        on = ' class="is-on"' if active == page else ""
        links.append(f'<a{on} href="{page}.html">{label}</a>')
    return (f'<header class="masthead"><span class="wordmark">Context<b>MAX</b><small>{escape(proj.name)}</small></span>'
            f'<nav class="tabs" aria-label="Pages">{"".join(links)}</nav><span class="spacer"></span>'
            f'<button type="button" class="iconbtn" id="theme">Dark</button></header>')


def _app_page(proj, title: str, active: str, targets, data: dict, script: str, find_hint: str, vis: bool) -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)} · {escape(proj.name)}</title>"
        '<link rel="stylesheet" href="cmx.css"><script src="cmx.js"></script>'
        + ('<script src="vis-network.min.js"></script>' if vis else "")
        + f'</head><body class="app" data-page="{escape(active)}">'
        + _nav(proj, active, targets)
        + '<div class="toolbar"><div class="views" id="views" role="group" aria-label="Views"></div>'
          '<div id="controls" class="hstack" style="margin:0"></div><div id="crumbs" class="crumbs"></div>'
          f'<label class="search"><span class="quiet">Find</span><input id="find" placeholder="{escape(find_hint)}"></label></div>'
          '<main class="stage"><div class="canvas" id="canvas"></div><aside class="drawer" id="drawer" aria-live="polite"></aside></main>'
        + f'<script type="application/json" id="cmx-data">{util.html_json(data)}</script>'
        + f'<script src="{script}"></script></body></html>\n')


def _targets_with_maps(proj) -> list[dict]:
    out = []
    for t in proj.code_targets:
        s = util.load_json(proj.code_dir / t["name"] / "overview.json", default=None)
        if s:
            langs = ", ".join(f"{k} {v}" for k, v in (s.get("languages") or {}).items())
            parts = []
            if s.get("functions_count"):
                parts.append(f"{s['functions_count']} function{'s' if s['functions_count'] != 1 else ''}")
            if s.get("vhdl"):
                parts.append(f"{s['vhdl']['entities_count']} VHDL entities")
            if langs:
                parts.append(langs)
            out.append({"name": t["name"], "label": t["label"], "summary": " · ".join(parts) or "no code found"})
    return out


LARGE_BYTES = 8_000_000          # the document list and function lists together: pages in parallel above it


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _page_file(job: tuple) -> str:
    return f"code-{job[1]}.html" if job[0] == "code" else f"{job[0]}.html"


def _page(job: tuple) -> tuple[str, str]:
    """One page written (a piece of parallel work): its file name, and what it shows."""
    d = parallel.shared()
    proj, portable, targets = d["proj"], d["portable"], d["targets"]
    out = proj.pages_dir
    if job[0] == "code":
        t = next(x for x in targets if x["name"] == job[1])
        full = next(x for x in proj.code_targets if x["name"] == t["name"])
        data = code_data.build(proj, full, portable)
        data["project"] = {"name": proj.name, "targets": targets, "links": d["links"][:12]}
        util.save_text(out / _page_file(job), _app_page(proj, f"Code: {t['label']}", f"code-{t['name']}", targets, data,
                                                        "code.js", "function or module", vis=True))
        return _page_file(job), f"the code map of {t['label']}"
    if job[0] == "documents":
        data = docs_data.build(proj, portable)
        util.save_text(out / "documents.html", _app_page(proj, "Documents", "documents", targets, data, "documents.js",
                                                     "title or document number", vis=True))
        return "documents.html", "the document map"
    if job[0] == "params":
        values_data = params_data.build(proj, portable)
        values_data["project"] = proj.slug
        util.save_text(out / "params.html", _params_page(proj, targets, values_data))
        return "params.html", "the values and where each is stated"
    data = atlas_data.build(proj, portable)
    util.save_text(out / "atlas.html", _app_page(proj, "Complete Atlas", "atlas", targets, data, "atlas.js",
                                             "module, document or function", vis=False))
    return "atlas.html", "the Complete Atlas, code and documents and every link"


def build_all(proj, portable: bool = False) -> dict:
    out = proj.pages_dir
    out.mkdir(parents=True, exist_ok=True)
    for name in SHARED:
        shutil.copyfile(ASSETS / name, out / name)
    targets = _targets_with_maps(proj)
    links = [f"{c.get('from')} → {c.get('to')}: {c.get('label', c.get('kind', ''))}" for c in _connections(proj)]
    jobs = [("code", t["name"]) for t in targets]
    if (proj.documents_dir / "doc-list.jsonl").exists():
        jobs += [("documents",), ("params",)]
    if jobs:
        jobs.append(("atlas",))
    # each page is written by a worker of its own on a large project (each reads what it shows, and writes
    # its own file); on a small one, starting the workers would take longer than writing the pages here
    large = _size(proj.documents_dir / "doc-list.jsonl") + sum(
        _size(proj.code_dir / t["name"] / "function-list.jsonl") for t in targets) > LARGE_BYTES
    written = []
    with parallel.Spread(_page, jobs, data={"proj": proj, "portable": portable, "targets": targets, "links": links},
                         min_items=2 if large else len(jobs) + 1) as spread:
        for _, result in spread.results():
            if isinstance(result, BaseException):
                raise result
            util.say("pages", f"{result[0]}: {result[1]}")
    written = [_page_file(job) for job in jobs]
    sdata = {"targets": targets, "links": _connections(proj), "project": proj.name,
             "file": str(proj.path("notes", "connections.json")) if not portable else "notes/connections.json"}
    util.save_text(out / "connections.html", _connections_page(proj, targets, sdata))
    written.append("connections.html")
    # pages of code bases that left the project
    keep = set(written) | set(SHARED)
    for f in out.glob("*.html"):
        if f.name not in keep:
            f.unlink()
    util.say("views", f"{len(written)} pages in {out}")
    return {"pages": written}


def _connections(proj) -> list[dict]:
    data = util.load_json(proj.path("notes", "connections.json"), default=None)
    if isinstance(data, dict):
        data = data.get("connections", [])
    return [c for c in (data or []) if isinstance(c, dict) and c.get("from") and c.get("to")]


def _params_page(proj, targets, data: dict) -> str:
    st = data["stats"]
    note = ("" if not st["truncated"] else
            '<p class="quiet">This page holds the most widely stated values; the full value list is in '
            "documents/params.sqlite and answers <span class=\"fixed\">contextmax params</span>.</p>")
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Parameters · {escape(proj.name)}</title><link rel=\"stylesheet\" href=\"cmx.css\"><script src=\"cmx.js\"></script></head>"
        '<body class="page">' + _nav(proj, "params", targets) +
        '<div class="column" style="gap:20px">'
        '<div class="hstack" style="align-items:flex-end;gap:18px"><div style="display:flex;flex-direction:column;gap:6px">'
        '<label for="find" class="quiet">Name of the value</label>'
        '<input id="find" class="fixed" style="width:320px;max-width:100%;min-height:42px;padding:8px 12px;border:1.5px solid var(--text);border-radius:8px;background:var(--surface)" placeholder="settle time"></div>'
        '<p class="quiet" style="max-width:560px;margin:0;line-height:21px">A value is found by its name. The number alone is ambiguous: '
        f'{st["rows_count"]:,} values are indexed, {st["named_variables_count"]:,} names, {st["shared_count"]:,} stated in more than one document, '
        f'<b style="color:var(--conflict)">{st["differ_count"]:,}</b> of those with different numbers; '
        f'{st.get("in_code_count", 0):,} found in the code, <b style="color:var(--conflict)">{st.get("code_mismatch_count", 0):,}</b> '
        'of them with another value there.</p></div>'
        '<div class="hstack" role="group" aria-label="Show">'
        '<button type="button" class="switch is-on" data-only="all" aria-pressed="true">All names</button>'
        '<button type="button" class="switch" data-only="shared" aria-pressed="false">In more than one document</button>'
        '<button type="button" class="switch" data-only="differ" aria-pressed="false">Disagreeing</button>'
        '<button type="button" class="switch" data-only="code" aria-pressed="false">In the code</button></div>'
        + note +
        '<div style="display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start">'
        '<div class="tile" style="flex:1 1 300px;max-width:420px;max-height:70vh;overflow:auto;padding:14px"><ul id="vars" class="drawer" style="width:auto;border:0;padding:0;background:none"></ul></div>'
        '<div id="detail" style="flex:999 1 560px;min-width:0"></div></div></div>'
        f'<script type="application/json" id="cmx-data">{util.html_json(data)}</script><script src="params.js"></script></body></html>\n')


def _connections_page(proj, targets, data: dict) -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Connections · {escape(proj.name)}</title><link rel=\"stylesheet\" href=\"cmx.css\"><script src=\"cmx.js\"></script></head>"
        '<body class="app">' + _nav(proj, "connections", targets) +
        '<div class="toolbar"><b>Connections</b><span class="quiet">Each double box is one code base. Lines are links a call graph cannot see '
        '(between programs, chips and devices), written by hand with the code that proves them.</span></div>'
        '<main class="stage"><div class="canvas" id="canvas"></div><aside class="drawer" id="drawer"></aside></main>'
        f'<script type="application/json" id="cmx-data">{util.html_json(data)}</script><script src="connections.js"></script></body></html>\n')
