# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""manifest.json: provenance, the two identity hashes and the completeness verdict.

`baseline_identity_hash` answers "did the same material go in?": semantic config, engine
version and hash, and the sorted list of every source file's content hash.
`artifact_identity_hash` answers "did the same artifacts come out?": the hash of every
deterministic artifact in the index folder. Timestamps, machine paths, caches, logs and the
derived query store are deliberately outside both.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

from contextmax import version
from contextmax.config import Config
from contextmax.io.canon import rel_key, sha256_json
from contextmax.io.hash import sha256_file
from contextmax.paths import Layout

# Top-level entries of the index folder that are never part of the artifact identity.
EXCLUDED_FROM_IDENTITY = frozenset(
    {
        "manifest.json",
        "build-state.json",
        "README.md",
        "config.json",
        "index-path.txt",
        "cache",
        "logs",
        "query.sqlite",
        ".contextmax-skip",
        "skill",  # the rendered skill names this machine's paths on purpose
    }
)


def engine_hash() -> str:
    """SHA-256 over the engine's own source and data files (sorted), so the code is provenance."""
    package_dir = Path(version.__file__).parent
    digest = hashlib.sha256()
    for path in sorted(package_dir.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        if path.suffix not in (".py", ".json", ".md", ".js", ".css", ".html", ".tmpl"):
            continue
        digest.update(rel_key(str(path.relative_to(package_dir))).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def collect_artifact_hashes(layout: Layout) -> dict[str, str]:
    hashes: dict[str, str] = {}
    index = layout.index
    if not index.is_dir():
        return hashes
    for path in sorted(index.rglob("*")):
        if path.is_dir():
            continue
        rel = rel_key(str(path.relative_to(index)))
        top = rel.split("/", 1)[0]
        if top in EXCLUDED_FROM_IDENTITY or rel in EXCLUDED_FROM_IDENTITY:
            continue
        if path.name.endswith(".tmp") or ".tmp-" in path.name:
            continue
        hashes[rel] = sha256_file(path)
    return dict(sorted(hashes.items()))


def completeness(build_state: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    stages = build_state.get("stages", {})
    enabled = {name: st for name, st in stages.items() if st.get("enabled")}
    failed = sorted(
        name for name, st in enabled.items() if st.get("attempted") and st.get("ok") is False
    )
    not_run = sorted(
        name for name, st in enabled.items() if st.get("implemented") and not st.get("attempted")
    )
    unimplemented = sorted(name for name, st in stages.items() if not st.get("implemented"))
    verdict = "full" if not failed and not not_run else "partial"
    return {
        "verdict": verdict,
        "failed_stages": failed,
        "stages_not_run": not_run,
        "unimplemented_stages": unimplemented,
        "n_problems": len(build_state.get("problems", [])),
        "n_skipped": coverage.get("n_skipped", 0),
        "n_tier_c": coverage.get("by_tier", {}).get("C", 0),
        "n_tier_d": coverage.get("by_tier", {}).get("D", 0),
        "n_grammar_missing": coverage.get("by_skip_reason", {}).get("grammar-missing", 0),
        "n_missing_dependency": coverage.get("by_skip_reason", {}).get("missing-dependency", 0),
        "n_read_errors": coverage.get("by_skip_reason", {}).get("read-error", 0),
        "n_cloud_placeholders": coverage.get("by_skip_reason", {}).get("cloud-placeholder", 0),
        "n_scans_detected": coverage.get("documents", {}).get("n_scans_detected", 0),
        "n_truncated": coverage.get("documents", {}).get("n_truncated", 0),
    }


def build_manifest(
    *,
    layout: Layout,
    config: Config,
    files: list[dict[str, Any]],
    build_state: dict[str, Any],
    coverage: dict[str, Any],
    adapters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = sorted([row["file"], row["sha256"]] for row in files if row.get("sha256"))
    unhashed = sorted(row["file"] for row in files if not row.get("sha256"))
    baseline_identity = {
        "engine_version": version.__version__,
        "schema_version": version.SCHEMA_VERSION,
        "engine_sha256": engine_hash(),
        "config_semantic_sha256": config.semantic_hash(),
        "sources_sha256": sha256_json(sources),
        "n_sources": len(sources),
        "n_unhashed_sources": len(unhashed),
    }
    artifact_hashes = collect_artifact_hashes(layout)
    return {
        "engine": version.ENGINE_ID,
        "engine_version": version.__version__,
        "schema_version": version.SCHEMA_VERSION,
        "project_slug": config.slug,
        "project_name": config.name,
        "generated_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline_identity": baseline_identity,
        "baseline_identity_hash": sha256_json(baseline_identity),
        "artifact_hashes": artifact_hashes,
        "artifact_identity_hash": sha256_json(artifact_hashes),
        "adapters": adapters or {},
        "completeness": completeness(build_state, coverage),
        "build_run": {
            "started_utc": build_state.get("started_utc"),
            "config_hash": build_state.get("config_hash"),
        },
    }
