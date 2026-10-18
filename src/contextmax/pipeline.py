"""The build, in order: catalogue, text cache, code maps, document map, gate, views, manifest.

Four depths, from quick to complete:
  quick (default)    code maps, the document map from the text already cached, views, build info
  --catalogue        the file catalogue only
  --documents        catalogue, then new or changed documents read (incremental), then everything
  --full             everything, with failed documents retried and the cache reconciled

Read-only on the project's folders; everything is written into the working folder.
A failing validation gate stops the build before any view is written.
"""
from __future__ import annotations

import time

from contextmax import catalogue, util
from contextmax.code import run as code_run
from contextmax.docs import corpus, textcache
from contextmax.project import Project


class GateFailed(SystemExit):
    pass


def _plan(proj: Project, depth: str) -> list[str]:
    """The steps this build takes, in order, as the log numbers them."""
    listed = depth in ("catalogue", "documents", "full") or not (proj.catalogue_dir / "all-files.csv").exists()
    if depth == "catalogue":
        return ["catalogue"] + (["gate"] if (proj.documents_dir / "doc-list.jsonl").exists() else []) + ["pages"]
    read = depth in ("documents", "full") or not (proj.documents_dir / "text-index.jsonl").exists()
    return (["catalogue"] if listed else []) + (["read"] if read else []) + ["code", "docmap", "gate", "pages"]


def build(proj: Project, depth: str = "quick", ocr: bool = True) -> dict:
    t0 = time.time()
    report = {"depth": depth}
    textcache.migrate(proj)                   # an index from before 0.4.1 names its text hashes the new way
    steps = util.Steps(_plan(proj, depth))
    util.live("start", project=proj.name, depth=depth)
    if "catalogue" in steps.names:
        steps.start("catalogue")
        report["catalogue"] = catalogue.build(proj)
        util.live("catalogue", files=report["catalogue"]["files"])
        if depth == "catalogue":
            if "gate" in steps.names:
                steps.start("gate")
                gate(proj, report)            # the pages are written again from the document map on disk
            steps.start("pages")
            _finish(proj, report)
            steps.end()
            _summary(proj, report, time.time() - t0)
            return report
    if "read" in steps.names:
        steps.start("read")
        report["text_cache"] = textcache.build(proj, scope="all", resume=True, prune=True,
                                               retry_unreadable=(depth == "full"), ocr=ocr)
    steps.start("code")
    report["code"] = code_run.build(proj)
    if util.live_on():
        from contextmax.views import atlas_data
        atlas_data.live_code(proj)
    steps.start("docmap")
    report["corpus"] = corpus.build(proj)
    steps.start("gate")
    gate(proj, report)
    steps.start("pages")
    _finish(proj, report)
    steps.end()
    _summary(proj, report, time.time() - t0)
    util.say("done", f"{proj.name} built in {time.time() - t0:.1f} s")
    util.live("done", seconds=round(time.time() - t0, 1))
    return report


def gate(proj: Project, report: dict | None = None) -> None:
    """The document map's strict checks; a failure stops before any page is written."""
    util.live("gate", state="checking")
    util.say("gate", "checking every document, link and value against the files on disk")
    errors, counts = corpus.validate(proj)
    if report is not None:
        report["validation"] = {"errors": errors[:50], "errors_count": len(errors), "counts": counts}
    util.live("gate", state="failed" if errors else "passed", errors=len(errors), counts=counts)
    if errors:
        util.say("gate", "DOCUMENT MAP VALIDATION FAILED")
        for e in errors[:30]:
            util.say("gate", "  - " + e)
        raise GateFailed(1)
    util.say("gate", "validation passed: " + ", ".join(f"{v} {k}" for k, v in counts.items()))


def _finish(proj: Project, report: dict) -> None:
    """Views, manifest and home page. Imported late: they read everything above."""
    from contextmax import buildinfo, home
    from contextmax.views import render

    util.live("pages")
    if (proj.documents_dir / "doc-list.jsonl").exists() or (proj.code_dir / "codebases.json").exists():
        report["pages"] = render.build_all(proj)["pages"]
    util.say("pages", "build info: what was read, and the fingerprints of the index")
    report["manifest"] = buildinfo.build(proj)
    home.build(proj)
    util.say("pages", "Home.html")


def _n(x) -> str:
    return f"{int(x or 0):,}"


def _summary(proj: Project, report: dict, seconds: float) -> None:
    """What this build made, in a few lines at the end of the log: read from build info, the one record."""
    m = util.load_json(proj.workspace / "buildinfo.json", default={}) or {}
    comp, cat, ts, dm = m.get("completeness") or {}, report.get("catalogue") or {}, m.get("text_store") or {}, m.get("corpus") or {}
    rows = []
    files = (m.get("catalogue") or {}).get("file_total")
    if files is not None:
        line = f"{_n(files)} in {util.count(len(proj.folders), 'folder')}"
        if cat.get("changes"):
            line += f" ({cat['changes']} since the last catalogue)"
        rows.append(("files", line))
    if ts.get("docs_count") is not None:
        line = f"{_n(ts['docs_count'])} read"
        read_now = report.get("text_cache") or {}
        if read_now:
            line += f"; {_n(read_now.get('read_now'))} new or changed read now"
            if read_now.get("ocr_now"):
                line += f", {_n(read_now['ocr_now'])} by text recognition"
        extra = [f"{_n(comp[k])} {w}" for k, w in (("unreadable_count", "unreadable"), ("pending_count", "still in the cloud"),
                                                     ("scans_unread_count", "scans without text")) if comp.get(k)]
        rows.append(("documents", line + (" (" + ", ".join(extra) + ")" if extra else "")))
    for name, cb in (m.get("code_bases") or {}).items():
        vh = ((report.get("code") or {}).get(name) or {}).get("vhdl")
        parts = []
        if cb.get("functions_count") or not vh:
            parts.append(", ".join(util.count(int(cb.get(k) or 0), w) for k, w in (
                ("files_count", "file"), ("functions_count", "function"), ("call_edges_count", "call"), ("modules_count", "module"))))
        if vh:
            parts.append(f"VHDL {util.count(int(vh.get('entities_count') or 0), 'entity', 'entities')}")
        rows.append(("code", f"{cb.get('label')}: " + "; ".join(parts)))
    if dm.get("docs_count") is not None:
        kinds = dm.get("doc_doc_kinds") or {}
        rows.append(("links", f"{_n(dm.get('doc_doc_edges_count'))} between documents"
                              + (" (" + ", ".join(f"{k} {_n(v)}" for k, v in sorted(kinds.items())) + ")" if kinds else "")
                              + f"; {_n(dm.get('doc_code_edges_count'))} from {_n(dm.get('code_linked_count'))} documents to the code"))
        conflicts = int(dm.get("value_conflicts_count") or 0)
        named = int(dm.get("named_values_count") or 0)
        rows.append(("values", f"{util.count(int(dm.get('param_rows') or 0), 'value')}, each with its line"
                               + (f"; {_n(named)} with a name ({_n(dm.get('names_from_sentences_count'))} named by their "
                                  f"sentence), {util.count(int(dm.get('value_names_count') or 0), 'name')}" if named else "")
                               + (f"; {util.count(conflicts, 'name')} with more than one value" if conflicts else "")))
        vc = dm.get("value_code") or {}
        named_in_code = sum(int((cb or {}).get("values_count") or 0) for cb in (report.get("code") or {}).values())
        if vc.get("pairs_count") or named_in_code:
            rows.append(("in code", f"{util.count(named_in_code, 'named number')} in the code; "
                                    f"{util.count(int(vc.get('names_count') or 0), 'value name')} of the documents found there"
                                    + (" (" + ", ".join(f"{k} {_n(v)}" for k, v in (vc.get("outcomes") or {}).items()) + ")"
                                       if vc.get("outcomes") else "")))
    v = report.get("validation")
    if v:
        rows.append(("gate", "passed" if not v.get("errors_count") else f"{v['errors_count']} problems"))
    pages = len(report.get("pages") or []) + (1 if (proj.workspace / "Home.html").exists() else 0)
    rows.append(("pages", f"{util.count(pages, 'page')} · confidence {comp.get('confidence', '?')}"
                          + (f" ({comp['confidence_reason']})" if comp.get("confidence") != "High" and comp.get("confidence_reason") else "")))
    print(f"\n=== Summary · {proj.name} · built in {util.clock(seconds)}", flush=True)
    for label, text in rows:
        print(f"    {label:<10} {text}", flush=True)
    for p in comp.get("problems") or []:
        print(f"    {'note':<10} {p}", flush=True)
    unpaged = int((util.load_json(proj.documents_dir / "text-coverage.json", default={}) or {}).get("ocr_unpaged_count") or 0)
    if unpaged:
        print(f"    {'note':<10} {util.count(unpaged, 'scan')} recognised before ContextMAX recorded pages: their values "
              "cite a line, not a page. Read everything again (full) to add the pages", flush=True)
