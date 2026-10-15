"""buildinfo.json: what was mapped, what was made, how complete it is, and fingerprints to prove it.

Two identities, kept apart on purpose:
  inputs_hash   the source that was mapped: every code file's bytes, and every
                           document's extracted text with its source date and size
  outputs_hash   what this build wrote about the project: the catalogue, the code maps and the
                 document map with its value database
Timestamps, machine paths, the pages (they hold this PC's paths) and which Office programs this PC
has are recorded, but outside both hashes, so two machines that map the same folders get the same
two numbers.

Completeness is stated, never assumed: a build that could not read some documents, that
left files waiting in the cloud or found scans it could not read says so, and the status line
an AI writes under its answers comes from here.
"""
from __future__ import annotations

import sys
from pathlib import Path

from contextmax import VERSION, util
from contextmax.catalogue import SKIP_DIR_NAMES
from contextmax.code import c_lang, cpp_lang, matlab_lang, python_lang, vhdl_lang
from contextmax.code.common import list_sources

CODE_SUFFIXES = (c_lang.EXTENSIONS | cpp_lang.EXTENSIONS | python_lang.EXTENSIONS | matlab_lang.EXTENSIONS
                 | vhdl_lang.EXTENSIONS)


def _hash_dir(d: Path, skip: set[str] = frozenset()) -> dict[str, str]:
    out = {}
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name not in skip and not p.name.endswith(".tmp"):
            out[util.rel_key(p, d)] = util.hash_file(p)
    return out


def build(proj) -> dict:
    ws = proj.workspace
    code_bases, source_hashes = {}, {}
    for t in proj.code_targets:
        d = proj.code_dir / t["name"]
        if not (d / "overview.json").exists():
            continue
        files = list_sources(Path(t["root"]), CODE_SUFFIXES, set(SKIP_DIR_NAMES))
        src = util.canonical_hash([[rel, util.hash_file(full)] for full, rel in files])
        content = _hash_dir(d)
        s = util.load_json(d / "overview.json", default={})
        code_bases[t["name"]] = {"label": t["label"], "languages": s.get("languages", {}), "files_count": s.get("files_count"),
                                "functions_count": s.get("functions_count"), "call_edges_count": s.get("call_edges_count"),
                                "modules_count": s.get("modules_count"), "indirect_calls_count": s.get("indirect_calls_count"),
                                "ambiguous_calls_count": s.get("ambiguous_calls_count"),
                                "tree_hash": src, "fingerprint": util.canonical_hash(content),
                                "bytes_sha256": content}
        source_hashes[t["name"]] = src
    index_rows = util.load_jsonl(proj.documents_dir / "text-index.jsonl")
    docs_identity = util.canonical_hash([[r["key"], r["sha256"], r.get("file_bytes"), r.get("file_mtime_utc")]
                                         for r in index_rows])
    text_meta = util.load_json(proj.documents_dir / "text-info.json", default={}) or {}
    coverage = util.load_json(proj.documents_dir / "text-coverage.json", default={}) or {}
    doc_files = {}
    for name in ("doc-list.jsonl", "doc-sources.jsonl", "doc-outlines.jsonl", "params.jsonl", "params.sqlite",
                 "params-info.json", "text-index.jsonl", "text-coverage.json", "overview.json", "document-guide.md",
                 "links/doc-to-code.jsonl", "links/between-docs.jsonl", "links/code-to-doc.json"):
        p = proj.documents_dir / name
        if p.exists():
            doc_files[name] = util.hash_file(p)
    catalogue = {name: util.hash_file(proj.catalogue_dir / name) for name in ("all-files.csv", "priority-files.csv", "overview.txt", "folders.json")
                 if (proj.catalogue_dir / name).exists()}
    pages = _hash_dir(proj.pages_dir)
    dm_summary = util.load_json(proj.documents_dir / "overview.json", default={}) or {}
    folders = util.load_json(proj.catalogue_dir / "folders.json", default={}) or {}

    pending_count = int(coverage.get("pending_count") or 0)
    skipped_count = int(coverage.get("skipped_count") or 0)
    scans_count = int(coverage.get("scanned_unread_count") or 0)
    cached_count = int(coverage.get("cached_count") or 0)
    missing_folders = [f["name"] for f in folders.get("folders", []) if not f.get("found")]
    code_expected = [t["name"] for t in proj.code_targets]
    complete = {
        "code_ok": all(t in code_bases for t in code_expected),
        "missing_code_bases": [t for t in code_expected if t not in code_bases],
        "with_catalogue": bool(catalogue),
        "with_text_store": bool(index_rows),
        "with_doc_map": bool(doc_files.get("doc-list.jsonl")),
        "with_params": bool(doc_files.get("params.sqlite")),
        "docs_ok": bool(index_rows) and pending_count == 0 and not missing_folders,
        "missing_folders": missing_folders,
        "pending_count": pending_count, "unreadable_count": skipped_count, "scans_unread_count": scans_count, "cached_count": cached_count,
    }
    problems = []
    if missing_folders:
        problems.append(f"{len(missing_folders)} folder(s) not found")
    if not complete["code_ok"]:
        problems.append("a code base was not mapped")
    if pending_count:
        problems.append(f"{pending_count} file(s) still in the cloud")
    share = skipped_count / max(1, cached_count + skipped_count)
    if share > 0.05:
        problems.append(f"{skipped_count} unreadable documents")
    if scans_count:
        problems.append(f"{scans_count} scan(s) without text")
    partial_count = int(coverage.get("ocr_partial_count") or 0)
    if partial_count:
        problems.append(f"{partial_count} scan(s) recognised only in part")
    doubtful_count = int(coverage.get("ocr_doubtful_count") or 0)
    if doubtful_count:
        problems.append(f"{doubtful_count} scan(s) with pages whose recognised text does not read as words")
    if not problems:
        confidence, reason = "High", "every folder read"
    elif missing_folders or not complete["code_ok"] or not complete["with_doc_map"]:
        confidence, reason = "Low", problems[0]
    else:
        confidence, reason = "Medium", problems[0]
    complete.update({"extent": "full" if not problems else "partial", "confidence": confidence,
                     "confidence_reason": reason, "problems": problems})

    # The pages hold this PC's paths (editor links) and folders.json the folder locations, so
    # both stay out of the identity; everything that describes the project itself is in it.
    artifacts = {"catalogue": {k: v for k, v in catalogue.items() if k != "folders.json"},
                 "code_bases": {k: v["fingerprint"] for k, v in code_bases.items()},
                 "corpus": doc_files}
    manifest = {
        "contextmax_version": VERSION,
        "project": {"name": proj.name, "slug": proj.slug,
                    "folders": [{"name": f.name, "holds": f.holds} for f in proj.folders]},
        "built_utc": util.utc_now(),
        "inputs_hash": util.canonical_hash({"code": source_hashes, "documents": docs_identity}),
        "outputs_hash": util.canonical_hash(artifacts),
        "completeness": complete,
        "code_bases": code_bases,
        "text_store": {"docs_count": len(index_rows), "methods": text_meta.get("methods", {}),
                                "extensions": text_meta.get("extensions", {}), "docs_hash": docs_identity,
                                "coverage": coverage},
        "corpus": {**{k: dm_summary.get(k) for k in ("docs_count", "sources_count", "code_linked_count", "doc_code_edges_count",
                                                          "doc_doc_edges_count", "doc_doc_kinds", "outline_totals",
                                                          "param_rows", "param_origins")},
                         "bytes_sha256": doc_files},
        "catalogue": {"file_total": folders.get("file_total"), "bytes_sha256": catalogue},
        "pages_sha256": pages,
        "environment": {"readers": text_meta.get("readers", {}), "workspace": str(ws), "python": sys.version.split()[0]},
        "note": "inputs_hash identifies the mapped source; outputs_hash identifies what was built "
                "from it. built_utc and environment are outside both.",
    }
    util.save_json(ws / "buildinfo.json", manifest, indent=2)
    return {"inputs_hash": manifest["inputs_hash"],
            "outputs_hash": manifest["outputs_hash"], "confidence": confidence}
