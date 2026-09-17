# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""The edge envelope shared by every relation."""

from __future__ import annotations

from typing import Any

STATUSES = ("resolved", "ambiguous", "unresolved", "external")


def edge_row(
    *,
    src: str,
    dst: str | None,
    rel: str,
    tier: str,
    confidence: str | None,
    evidence: str,
    adapter: str,
    status: str = "resolved",
    dst_name: str | None = None,
    count: int = 1,
    sites: list[dict[str, Any]] | None = None,
    candidates: list[str] | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    assert status in STATUSES, status
    return {
        "src": src,
        "dst": dst,
        "dst_name": dst_name,
        "rel": rel,
        "kind": kind,
        "tier": tier,
        "confidence": confidence,
        "evidence": evidence,
        "status": status,
        "count": count,
        "sites": sites or [],
        "candidates": sorted(candidates or []),
        "adapter": adapter,
    }
