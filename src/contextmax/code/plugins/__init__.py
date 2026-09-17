# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Tier A language plugins.

`AVAILABLE` lists the plugin ids importable in this installation; `analyzer(plugin_id)` returns
the analyze function. A plugin id is what `registry/languages.json` names in its `plugin` field.
"""

from __future__ import annotations

from collections.abc import Callable

from contextmax.code.base import FileAnalysis

AVAILABLE: frozenset[str] = frozenset({"python"})


def analyzer(plugin_id: str) -> Callable[[str, str, str | None], FileAnalysis] | None:
    if plugin_id == "python":
        from contextmax.code.plugins import python

        return python.analyze
    return None


def adapter_id(plugin_id: str) -> str | None:
    if plugin_id == "python":
        from contextmax.code.plugins import python

        return python.PLUGIN_ID
    return None
