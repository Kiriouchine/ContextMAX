# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""A synthetic mixed project used by every test suite.

Built in-process, never checked in as binaries, and written in binary mode with explicit LF
newlines so the same bytes appear on every operating system. Grows with each phase; keep the
existing entries stable because golden files depend on them.
"""

from __future__ import annotations

import sys
from pathlib import Path

FILES: dict[str, bytes | str] = {
    "README.md": "# Sample project\n\nSee [the spec](docs/spec.md) and `src/app/main.py`.\n",
    "docs/spec.md": (
        "# Sample specification\n\n## 1 Scope\n\nThe servo shall hold position within 2.0 deg.\n\n"
        "## 2 Interfaces\n\nSee `helper` in `src/app/util.py`.\n"
    ),
    "docs/notes.txt": "plain notes about the bench\n",
    "src/app/__init__.py": "",
    "src/app/main.py": (
        "from app.util import helper\n\n\ndef main():\n    return helper() + 1\n\n\n"
        "if __name__ == '__main__':\n    main()\n"
    ),
    "src/app/util.py": 'def helper():\n    """Return one."""\n    return 1\n',
    "src/native/core.c": '#include "core.h"\n\nint core_add(int a, int b) {\n    return a + b;\n}\n',
    "src/native/core.h": "int core_add(int a, int b);\n",
    "src/web/index.js": "function render() {\n  return 1;\n}\nrender();\n",
    "hdl/top.vhd": "entity top is\nend entity;\n",
    "scripts/run.sh": "#!/usr/bin/env bash\necho hi\n",
    "scripts/noext": "#!/usr/bin/env python3\nprint('x')\n",
    "data/config.json": '{"a": 1, "b": [1, 2]}\n',
    "data/table.csv": "label,value,unit\nservo error,2.0,deg\n",
    "unknown.zzz": "some text in an unknown language\nfoo(bar)\n",
    "bin/blob.bin": b"\x00\x01\x02binary\x00data",
    "bin/photo.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
    "build/out.txt": "generated output\n",
    "vendor/lib.py": "x = 1\n",
    "tests/test_main.py": "def test_main():\n    assert True\n",
    ".gitignore": "build/\n*.log\n!keep.log\n",
    "logs/run.log": "log line\n",
    "logs/keep.log": "kept because negated\n",
    "nested/.contextmax-skip": "",
    "nested/inner.py": "print(1)\n",
    "ärm-note.md": "# Ärm\n",
    "zebra-note.md": "# Zebra\n",
    "a-1.md": "# a-1\n",
    "a1.md": "# a1\n",
    "empty.txt": "",
    "Makefile": "all:\n\techo build\n",
}


def build_corpus(root: Path, *, reverse: bool = False) -> Path:
    """Create the corpus under `root`; `reverse` writes files in the opposite order."""
    root = Path(root)
    items = sorted(FILES.items())
    if reverse:
        items = list(reversed(items))
    for rel, content in items:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        with open(path, "wb") as handle:
            handle.write(data)
    return root


if __name__ == "__main__":  # pragma: no cover
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    build_corpus(target)
    print(f"corpus written to {target.resolve()}")
