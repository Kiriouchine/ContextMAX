# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Adapter registry: adapter id -> implementation. Absence here means the format is
catalogued with the reason "adapter not implemented", never silently skipped."""

from __future__ import annotations

from functools import lru_cache

from contextmax.docs.base import FormatAdapter


@lru_cache(maxsize=1)
def adapters() -> dict[str, FormatAdapter]:
    from contextmax.docs.adapters.html import HtmlAdapter
    from contextmax.docs.adapters.latex import LatexAdapter
    from contextmax.docs.adapters.markdown import MarkdownAdapter
    from contextmax.docs.adapters.plain import PlainAdapter

    table: dict[str, FormatAdapter] = {}
    for adapter in (MarkdownAdapter(), PlainAdapter(), HtmlAdapter(), LatexAdapter()):
        table[adapter.id] = adapter
    return table


def get(adapter_id: str | None) -> FormatAdapter | None:
    if adapter_id is None:
        return None
    return adapters().get(adapter_id)


def implemented(adapter_id: str | None) -> bool:
    return adapter_id is not None and adapter_id in adapters()
