"""Share a portable copy of a project's index through a shared folder, and the self-check.

The shared copy is what colleagues open without installing anything: the home page, the
pages (rebuilt without any path from this PC), the code maps, the catalogue, the value
database and the document map. The extracted text stays on this PC. One person shares;
everyone else reads. A dry run lists what would be written; a real run asks you to type
SHARE, because a synced folder sends the copy to everyone who has access to it.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from contextmax import VERSION, checkup, query, util

DOCS_FILES = ["text-index.jsonl", "doc-list.jsonl", "doc-sources.jsonl", "doc-outlines.jsonl", "params.sqlite",
              "params-info.json", "text-coverage.json", "overview.json", "document-guide.md",
              "links/doc-to-code.jsonl", "links/between-docs.jsonl", "links/code-to-doc.json"]
CATALOGUE_FILES = ["all-files.csv", "priority-files.csv", "overview.txt"]


def _stage(proj, tmp: Path) -> list[Path]:
    """Build the portable copy in a temporary folder and return its files."""
    from contextmax import home
    from contextmax.views import render

    class Portable:
        """The project, seen from the shared folder: same data, pages written elsewhere."""

        def __init__(self, base, out):
            self.__dict__["_b"], self.__dict__["_o"] = base, out

        def __getattr__(self, k):
            return getattr(self._b, k)

        @property
        def pages_dir(self):
            return self._o / "pages"

    view = Portable(proj, tmp)
    render.build_all(view, portable=True)
    for name in CATALOGUE_FILES:
        src = proj.catalogue_dir / name
        if src.exists():
            (tmp / "catalogue").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, tmp / "catalogue" / name)
    for name in DOCS_FILES:
        src = proj.documents_dir / name
        if src.exists():
            (tmp / "documents" / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, tmp / "documents" / name)
    if proj.code_dir.exists():
        shutil.copytree(proj.code_dir, tmp / "code")
    man = util.load_json(proj.workspace / "buildinfo.json", default={}) or {}
    man["shared"] = {"made_by": VERSION, "at_utc": util.utc_now(), "kind": "portable",
                     "with_text_store": False,
                     "note": "Extracted text stays on the PC that made the copy; search and links work, quoting needs the original."}
    man.pop("environment", None)
    util.save_json(tmp / "buildinfo.json", man, indent=2)
    # the home page, written as if the shared folder were the working folder
    keep = proj.workspace
    try:
        proj.workspace = tmp
        home.build(proj, portable=True)
    finally:
        proj.workspace = keep
    return sorted(p for p in tmp.rglob("*") if p.is_file())


def share(proj, dest: str, dry_run: bool = False, yes: bool = False) -> int:
    from contextmax.docs import corpus

    dest_p = Path(dest)
    if (proj.documents_dir / "doc-list.jsonl").exists():
        errors, _counts = corpus.validate(proj)
        if errors:
            print("The document map fails its checks, so it is not shared. Build the project again first:")
            for e in errors[:10]:
                print("  - " + e)
            return 1
    with tempfile.TemporaryDirectory(prefix="cmx-share-") as t:
        tmp = Path(t)
        files = _stage(proj, tmp)
        total = sum(p.stat().st_size for p in files)
        print(f"Sharing {proj.name}: {len(files)} files, {total / 1048576:.1f} MB, to {dest_p}")
        print("The copy holds document titles, headings, requirement text and values from every folder of this project.")
        print("Check that everyone who can open the destination may see all of them.")
        if dry_run:
            for p in files:
                print(f"  would write {util.rel_key(p, tmp)}")
            return 0
        if not yes:
            if input("Type SHARE to write it: ").strip() != "SHARE":
                print("Cancelled; nothing was written.")
                return 1
        for p in files:
            target = dest_p / util.rel_key(p, tmp)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
        print(f"Shared. Colleagues open {dest_p / 'Home.html'}")
    return 0


def selfcheck(proj) -> int:
    """A verdict for the person at the screen, and a JSON file they can send to whoever helps."""
    s = query.status(proj)
    checks = checkup.checks()
    verdict = "ready" if s.get("built") and s["confidence"] == "High" and s["sync"] == "in sync" else "attention needed"
    data = {"contextmax_version": VERSION, "project": proj.slug, "verdict": verdict, "status": s,
            "checkup": checks, "python": sys.version.split()[0],
            "folders": [{"name": f.name, "holds": f.holds, "found": Path(f.path).is_dir()} for f in proj.folders]}
    out = proj.path("logs", f"self-check-{util.utc_now()[:10]}.json")
    util.save_json(out, data, indent=2)
    print(f"{proj.name}: {verdict}")
    print(query.status_line(proj, s))
    for p in s.get("problems") or []:
        print(f"  - {p}")
    for c in s.get("changes") or []:
        print(f"  - {c}")
    print(f"self-check: {out}")
    return 0 if verdict == "ready" else 1


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps({"usage": "contextmax share|selfcheck"}))
