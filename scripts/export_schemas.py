# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Write the JSON Schemas the engine validates against into docs/schema/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from contextmax.config import SCHEMA  # noqa: E402


def run() -> int:
    out = ROOT / "docs" / "schema"
    out.mkdir(parents=True, exist_ok=True)
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "ContextMAX config",
        **SCHEMA,
    }
    (out / "config.schema.json").write_text(
        json.dumps(schema, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {out / 'config.schema.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
