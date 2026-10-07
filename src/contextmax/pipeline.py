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


def build(proj: Project, depth: str = "quick", ocr: bool = True) -> dict:
    t0 = time.time()
    report = {"depth": depth}
    if depth in ("catalogue", "documents", "full") or not (proj.catalogue_dir / "all-files.csv").exists():
        report["catalogue"] = catalogue.build(proj)
        if depth == "catalogue":
            if (proj.documents_dir / "doc-list.jsonl").exists():
                gate(proj, report)            # the pages are written again from the document map on disk
            _finish(proj, report)
            return report
    if depth in ("documents", "full") or not (proj.documents_dir / "text-index.jsonl").exists():
        report["text_cache"] = textcache.build(proj, scope="all", resume=True, prune=True,
                                               retry_unreadable=(depth == "full"), ocr=ocr)
    report["code"] = code_run.build(proj)
    report["corpus"] = corpus.build(proj)
    gate(proj, report)
    _finish(proj, report)
    util.say("done", f"{proj.name} built in {time.time() - t0:.1f} s")
    return report


def gate(proj: Project, report: dict | None = None) -> None:
    """The document map's strict checks; a failure stops before any page is written."""
    errors, counts = corpus.validate(proj)
    if report is not None:
        report["validation"] = {"errors": errors[:50], "errors_count": len(errors), "counts": counts}
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

    if (proj.documents_dir / "doc-list.jsonl").exists() or (proj.code_dir / "codebases.json").exists():
        render.build_all(proj)
    report["manifest"] = buildinfo.build(proj)
    home.build(proj)
