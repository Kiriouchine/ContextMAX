# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""The stage ledger: saved after every stage so a crash still leaves a truthful record."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from contextmax.io.jsonl import read_json, write_json

# The full stage list from day one, so the ledger's shape never changes when stages land.
STAGES: tuple[str, ...] = (
    "discover",
    "code",
    "documents",
    "links",
    "graph",
    "catalogs",
    "viz",
    "skill",
    "manifest",
    "query",
)


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class BuildState:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {}

    def start(self, config_hash: str, engine_version: str, options: dict[str, Any]) -> None:
        self.data = {
            "config_hash": config_hash,
            "engine_version": engine_version,
            "started_utc": _now(),
            "finished_utc": None,
            "options": options,
            "stages": {
                name: {
                    "attempted": False,
                    "implemented": False,
                    "enabled": None,
                    "ok": None,
                    "error": "",
                    "seconds": 0.0,
                    "note": "",
                }
                for name in STAGES
            },
            "problems": [],
        }
        self.save()

    def mark(self, stage: str, **fields: Any) -> None:
        self.data["stages"][stage].update(fields)
        self.save()

    def problem(self, message: str) -> None:
        self.data["problems"].append(message)
        self.save()

    def finish(self) -> None:
        self.data["finished_utc"] = _now()
        self.save()

    def save(self) -> None:
        write_json(self.path, self.data)

    @classmethod
    def load(cls, path: Path) -> dict[str, Any] | None:
        path = Path(path)
        if not path.is_file():
            return None
        try:
            return read_json(path)
        except (OSError, ValueError):
            return None
