# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Tier B worker: parses files with tree-sitter in a separate process.

A grammar is native code and can crash on an unusual file. The worker streams one JSON line
per file (`{"start": key}` before, `{"done": key, ...}` after), so when it dies the parent knows
exactly which file killed it, records that, and restarts the worker on the rest.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

CRASH_HOOK_ENV = "CONTEXTMAX_TSWORKER_CRASH_ON"  # test hook: simulate a native crash on a key


def main() -> int:
    # The pipe carries JSON with arbitrary Unicode; never let a console code page decide.
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    payload = json.loads(sys.stdin.read())
    if payload.get("grammar_dir"):
        os.environ["CONTEXTMAX_GRAMMAR_DIR"] = payload["grammar_dir"]
    from contextmax.code import treesitter
    from contextmax.fs import os_path, read_text

    out = sys.stdout
    crash_on = os.environ.get(CRASH_HOOK_ENV)
    for entry in payload["files"]:
        key = entry["key"]
        out.write(json.dumps({"start": key}) + "\n")
        out.flush()
        if crash_on and key == crash_on:
            os._exit(139)
        try:
            text, _ = read_text(Path(os_path(Path(entry["path"]))))
            analysis = treesitter.analyze(key, text, entry["language"], entry["grammar"])
            record = {"done": key, "analysis": dataclasses.asdict(analysis)}
        except Exception as exc:
            record = {"done": key, "error": f"{exc.__class__.__name__}: {exc}"}
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
