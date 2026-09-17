# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""coverage.json: what was indexed, at which tier, and what was not, with counts by reason.

Deterministic by construction: no timestamps, every mapping sorted on write.
"""

from __future__ import annotations

from typing import Any

from contextmax.version import SCHEMA_VERSION


def build_coverage(
    discovery_counts: dict[str, Any], extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    counts = dict(discovery_counts)
    tiers = counts.get("by_tier", {})
    n_files = counts.get("n_files", 0)
    coverage = {
        "schema_version": SCHEMA_VERSION,
        "n_files": n_files,
        "n_dirs": counts.get("n_dirs", 0),
        "total_bytes": counts.get("total_bytes", 0),
        "n_excluded_dirs": counts.get("n_excluded_dirs", 0),
        "n_excluded_files": counts.get("n_excluded_files", 0),
        "n_skipped": counts.get("n_skipped", 0),
        "by_tier": {tier: tiers.get(tier, 0) for tier in ("A", "B", "C", "D")},
        "by_family": dict(sorted(counts.get("by_family", {}).items())),
        "by_language": dict(sorted(counts.get("by_language", {}).items())),
        "by_format": dict(sorted(counts.get("by_format", {}).items())),
        "by_role": dict(sorted(counts.get("by_role", {}).items())),
        "by_skip_reason": dict(sorted(counts.get("by_skip_reason", {}).items())),
        "by_excluded_by": dict(sorted(counts.get("by_excluded_by", {}).items())),
        "code": {
            "n_symbols": 0,
            "n_call_sites": 0,
            "n_resolved": 0,
            "n_ambiguous": 0,
            "n_unresolved": 0,
            "n_external": 0,
            "by_language": {},
        },
        "documents": {
            "n_documents": 0,
            "n_sections": 0,
            "n_terms": 0,
            "n_references": 0,
            "n_parameters": 0,
            "n_scans_detected": 0,
            "n_truncated": 0,
            "by_adapter": {},
            "by_determinism": {},
        },
        "links": {"n_edges": 0, "by_rel": {}, "by_confidence": {}},
    }
    if extra:
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(coverage.get(key), dict):
                coverage[key].update(value)
            else:
                coverage[key] = value
    return coverage
