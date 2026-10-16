"""Home.html: the front door of a project, with the numbers read live from what was built."""
from __future__ import annotations

from datetime import datetime
from html import escape

from contextmax import util


def _card(color: str, tag: str, big: str, unit: str, text: str, link: str, link_text: str) -> str:
    go = f'<a class="cta" href="{link}">{escape(link_text)}</a>' if link else '<span class="quiet">Nothing built yet</span>'
    return (f'<article class="tile"><div class="kicker"><i style="background:{color}"></i>{escape(tag)}</div>'
            f'<div class="hstack" style="margin:0;align-items:baseline"><span class="big">{big}</span>'
            f'<span class="quiet">{escape(unit)}</span></div><p>{text}</p>{go}</article>')


def build(proj, portable: bool = False) -> None:
    m = util.load_json(proj.workspace / "buildinfo.json", default={}) or {}
    comp = m.get("completeness", {})
    folders = util.load_json(proj.catalogue_dir / "folders.json", default={}) or {}
    cov = (m.get("text_store") or {}).get("coverage") or {}
    dmap = m.get("corpus") or {}
    codes = m.get("code_bases") or {}
    when = m.get("built_utc", "")
    try:
        when_txt = datetime.fromisoformat(when).astimezone().strftime("%d %b %Y, %H:%M")
    except ValueError:
        when_txt = when or "not built yet"
    conf = comp.get("confidence", "Low")
    dot = "" if conf == "High" else (" stale" if conf == "Medium" else " bad")
    file_total = (folders.get("file_total") or 0)
    noise = 0
    for r in util.csv_rows(proj.catalogue_dir / "all-files.csv"):
        if r["Category"].startswith("Noise"):
            noise += 1
    first_code = next(iter(codes), None)
    funcs_count = sum(v.get("functions_count") or 0 for v in codes.values())
    calls_count = sum(v.get("call_edges_count") or 0 for v in codes.values())
    ind_count = sum(v.get("indirect_calls_count") or 0 for v in codes.values())
    kinds = dmap.get("doc_doc_kinds") or {}
    st = dmap.get("outline_totals") or {}
    cards = [
        _card("var(--cat)", "Catalogue", f"{file_total:,}", f"files in {len(proj.folders)} folder{'s' if len(proj.folders) != 1 else ''}",
              f"{noise:,} noise files tagged, not hidden. {cov.get('skipped_count', 0):,} documents could not be read, each listed with its reason.",
              "catalogue/overview.txt", "Open the catalogue"),
        _card("var(--doc)", "Documents", f"{dmap.get('docs_count') or 0:,}", "documents",
              f"From {dmap.get('sources_count') or 0:,} files, copies folded in. {dmap.get('code_linked_count') or 0:,} name code; "
              f"{kinds.get('cites', 0):,} cite another, {kinds.get('shares', 0):,} share values; {st.get('requirements', 0):,} shall statements.",
              "pages/documents.html" if dmap.get("docs_count") else "", "Open the document map"),
        _card("var(--code)", "Code", f"{funcs_count:,}", f"functions in {len(codes)} code base{'s' if len(codes) != 1 else ''}",
              f"{calls_count:,} call{'s' if calls_count != 1 else ''} resolved. {ind_count:,} call{'s' if ind_count != 1 else ''} "
              "through pointers or objects not followed, and listed.",
              f"pages/code-{first_code}.html" if first_code else "", "Open the code map"),
        _card("var(--ok)", "Values", f"{dmap.get('param_rows') or 0:,}", "values with their source",
              "Every number with a unit, and every spreadsheet cell, found by its name.",
              "pages/params.html" if dmap.get("docs_count") else "", "Open the parameters"),
    ]
    mods_count = sum(v.get("modules_count") or 0 for v in codes.values())
    differ = dmap.get("value_conflicts_count") or 0
    atlas = ""
    if dmap.get("docs_count") or codes:
        atlas = ('<section><article class="tile" style="flex-direction:row;flex-wrap:wrap;align-items:center;gap:12px 28px">'
                 '<div style="flex:1;min-width:min(420px,100%)"><div class="kicker"><i style="background:var(--code)"></i>'
                 '<i style="background:var(--doc);margin-left:-4px"></i>Complete Atlas</div>'
                 f'<p style="margin:6px 0 0">The code, the documents and every link between them in one drawing: {mods_count:,} '
                 f"module{'s' if mods_count != 1 else ''} with their calls, {dmap.get('docs_count') or 0:,} documents by stage, "
                 f"{dmap.get('doc_code_edges_count') or 0:,} links from documents to code and {dmap.get('doc_doc_edges_count') or 0:,} "
                 "between documents"
                 + (f', <b style="color:var(--conflict)">{differ:,} value{"s" if differ != 1 else ""} that differ{"s" if differ == 1 else ""}</b>'
                    if differ else "")
                 + ". Click any module, document or line.</p></div>"
                 '<a class="cta" href="pages/atlas.html">Open the Complete Atlas</a></article></section>')
    rows = []
    for f in folders.get("folders", []):
        status = ('<span class="status ok">Read</span>' if f.get("found") else '<span class="status bad">Not found</span>')
        where = "(on the PC that made this copy)" if portable else f["path"]
        rows.append(f"<tr><td><b>{escape(f['name'])}</b></td><td class=\"fixed\" style=\"font-size:13px\">{escape(where)}</td>"
                    f"<td>{escape(f.get('holds', ''))}</td><td style=\"text-align:right\" class=\"fixed\">{f.get('files', 0):,}</td><td>{status}</td></tr>")
    if cov.get("pending_count"):
        rows.append(f'<tr><td colspan="5"><span class="status caution">{cov["pending_count"]} files are still in the cloud</span> '
                    "and will be read on the next build once they are downloaded.</td></tr>")
    code_links = "".join(f'<li><a href="pages/code-{escape(k)}.html">{escape(v.get("label", k))}</a> '
                         f'<span class="quiet">{v.get("functions_count", 0):,} functions</span></li>' for k, v in codes.items())
    problems = comp.get("problems") or []
    html = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(proj.name)} · ContextMAX</title><link rel=\"stylesheet\" href=\"pages/cmx.css\"><script src=\"pages/cmx.js\"></script></head>"
        '<body class="page"><header class="masthead"><span class="wordmark">Context<b>MAX</b>'
        f"<small>{escape(proj.name)}</small></span>"
        '<nav class="tabs"><a class="is-on" href="Home.html">Home</a>'
        + ('<a href="pages/atlas.html">Complete Atlas</a>' if atlas else "")
        + "".join(f'<a href="pages/code-{escape(k)}.html">{"Code" if len(codes) == 1 else "Code: " + escape(v.get("label", k))}</a>' for k, v in codes.items())
        + '<a href="pages/documents.html">Documents</a><a href="pages/params.html">Parameters</a><a href="pages/connections.html">Connections</a></nav>'
        '<span class="spacer"></span><button type="button" class="iconbtn" id="theme">Dark</button></header>'
        f'<div class="statusbar"><div class="in fixed"><span>Built {escape(when_txt)}</span>'
        f'<span><i class="lamp{dot}"></i>{"Every folder read" if not problems else escape("; ".join(problems))}</span>'
        f"<span>Confidence {escape(conf)}</span><span>Index {escape((m.get('outputs_hash') or '')[:12])}</span></div></div>"
        '<main class="column">'
        f'<section class="hstack" style="justify-content:space-between;align-items:flex-end;gap:16px"><div><h1 class="headline">{escape(proj.name)}</h1>'
        f'<p class="quiet" style="margin:6px 0 0;font-size:16px">{len(proj.folders)} folder{"s" if len(proj.folders) != 1 else ""} · '
        f'{file_total:,} files · built by scripts only, no AI in the build</p></div>'
        f'<p class="quiet" style="margin:0;max-width:420px">To update: <span class="fixed">contextmax build {escape(proj.slug)}</span>, '
        "or the Refresh button in the ContextMAX window.</p></section>"
        f'<section class="grid4">{"".join(cards)}</section>{atlas}'
        '<section><h2 class="sec">Your folders</h2><div class="tablebox"><table class="listing"><thead><tr><th>Name</th><th>Folder</th>'
        f'<th>Holds</th><th style="text-align:right">Files</th><th>State</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>'
        '<section class="grid4" style="grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr))">'
        '<article class="tile"><h2 class="sec" style="margin:0">Ask your AI</h2><p class="quiet">With the ContextMAX skill, an assistant '
        "answers in plain words and cites the file and line, the document, or the sheet and cell, and says what was not checked. "
        + ("" if portable else "It starts in the project's working folder, with the skill installed for it.") + "</p>"
        + ('<div class="hstack" id="ask-actions" style="margin:0" data-portable="1"></div>' if portable else
           f'<div class="hstack" id="ask-actions" style="margin:0" data-root="{escape(str(proj.workspace))}"></div>')
        + '<ul class="ask" style="list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px">'
        "<li>Where is this function defined, and who calls it?</li><li>What breaks if I change it?</li>"
        "<li>Where does this value come from, and do the documents agree?</li><li>Which documents describe this module?</li></ul></article>"
        f'<article class="tile"><h2 class="sec" style="margin:0">Code bases</h2><ul style="margin:0;padding-left:18px;line-height:26px">{code_links or "<li class=quiet>none mapped</li>"}</ul>'
        '<p class="quiet" style="margin-top:auto">Each opens in four views: bubbles, drafting table, metro lines and zoom levels.</p></article></section>'
        "</main>"
        '<footer class="pagefoot"><div class="in"><span>Same folders in, same index out. Source '
        f'<span class="fixed">{escape((m.get("inputs_hash") or "")[:12])}</span></span>'
        f"<span>ContextMAX {escape(m.get('contextmax_version', ''))} · made by Sev Kiriouchine</span></div></footer></body></html>\n")
    util.save_text(proj.workspace / "Home.html", html)
