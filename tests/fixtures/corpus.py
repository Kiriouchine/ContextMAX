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

from fixtures import office

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
    "docs/paper.pdf": b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n\x00\x00",
    "docs/report.docx": office.DOCX,
    "src/app/broken.py": b"print('x')\n\x00\x00binary junk\n",
    "bin/photo.png": office.PNG,
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
    # Documents: a LaTeX guide with sections, labels, refs, a figure, cites (no .bib) and an
    # include; the included file; an HTML page with headings and links; a plain report.
    "docs/guide.tex": (
        "\\documentclass{article}\n\\title{GPS Guide}\n\\begin{document}\n"
        "\\section{Introduction}\\label{sec:intro}\n"
        "The receiver is described in \\cite{ublox2011} and shown in Figure~\\ref{fig:setup}.\n"
        "Gains come from \\texttt{gain\\_sched} in gain_sched.m.\n"
        "\\subsection{Setup}\n\\begin{figure}\n\\includegraphics{bench.png}\n\\caption{The bench setup}\\label{fig:setup}\n\\end{figure}\n"
        "\\section{Method}\\label{sec:method}\nSee Section~\\ref{sec:intro} and \\ref{sec:missing}.\n"
        "\\begin{equation}\nx_{t+1} = A x_t + B u_t\n\\end{equation}\n"
        "\\input{intro}\n\\end{document}\n"
    ),
    "docs/intro.tex": "\\section{Background}\\label{sec:background}\nKalman filtering background.\n",
    "docs/page.html": (
        "<html><head><title>Tutorial</title><script>bad()</script></head><body>"
        '<h1>GPS tutorial</h1><p>See <a href="spec.md">the spec</a> and <a href="https://example.org/u">u-blox</a>.</p>'
        "<h2>Wiring</h2><ul><li>VCC to 3V3</li><li>TX to RX</li></ul></body></html>\n"
    ),
    "docs/report.txt": "Bench Report\n============\n\nThe servo error stayed below 2.0 deg.\n\n2 Results\n\nAll runs passed; see run_all.m.\n",
    # MATLAB: a function file with help text, a function it calls, a script with cells that
    # calls both and invokes another script by bare name (file-per-function resolution).
    "matlab/gain_sched.m": (
        "function [K, Ki] = gain_sched(v, table)\n"
        "% GAIN_SCHED Interpolate controller gains for airspeed v.\n"
        "%   [K, Ki] = GAIN_SCHED(v, table) returns proportional and integral gains.\n"
        "K = lookup_gain(v, table, 'kp');   % proportional\n"
        "Ki = lookup_gain(v, table, 'ki');\n"
        "x = v';\n"
        "end\n"
    ),
    "matlab/lookup_gain.m": (
        "function g = lookup_gain(v, table, name)\n"
        "% LOOKUP_GAIN Linear interpolation in a gain table.\n"
        "g = interp1(table.v, table.(name), v);\n"
        "end\n"
    ),
    "matlab/run_all.m": (
        "%% Load data\n"
        "load('flight.mat');\n"
        "table.v = [10 20 30];\n"
        "%% Schedule\n"
        "[K, Ki] = gain_sched(15, table);\n"
        "plot_results\n"
        "%{\n"
        "gain_sched(999, table)  % commented out, must not count\n"
        "%}\n"
    ),
    "matlab/plot_results.m": "% PLOT_RESULTS Draw the scheduled gains.\nfigure; plot(1:3);\n",
    # Shell: a function, a call to it, and a bare command that is not a symbol.
    "scripts/lib.sh": '#!/usr/bin/env bash\n# helper library\nlog_msg() {\n  echo "$1"\n}\n',
    "scripts/deploy.sh": "#!/usr/bin/env bash\nsource ./lib.sh\nlog_msg deploying\nrsync -a src/ dest/\n",
    # C: a header prototype, two definitions, a macro and a call chain.
    "src/native/util.c": (
        '#include "core.h"\n#include <stdio.h>\n#define SQUARE(x) ((x) * (x))\n\n'
        "static int helper_c(int v) {\n    return SQUARE(v);\n}\n\n"
        "int util_sum(int a, int b) {\n    /* adds via core_add */\n    return core_add(helper_c(a), b);\n}\n"
    ),
    # Phase 3 session 1: a BibTeX file resolving the guide's citation (and pointing at the
    # PDF), a notebook, RST, AsciiDoc, Org, an email with an attachment, config files of every
    # shape and a dependency manifest.
    "docs/refs.bib": (
        "@manual{ublox2011,\n  title = {u-blox 6 Receiver Description},\n  author = {{u-blox AG}},\n"
        "  year = 2011,\n  url = {https://www.u-blox.com/},\n  file = {:docs/paper.pdf:pdf}\n}\n"
        "@article{kalman1960, title={A New Approach to Linear Filtering}, author={Kalman, R. E.},\n"
        "  year={1960}, journal={J. Basic Eng.}, doi={10.1115/1.3662552}}\n"
    ),
    "docs/analysis.ipynb": '{"cells": [{"cell_type": "markdown", "source": ["# Gain analysis\\n", "\\n", "See gain_sched.m and docs/spec.md.\\n"]}, {"cell_type": "code", "execution_count": 1, "outputs": [], "source": ["K = gain_sched(10, table)\\n"]}], "metadata": {"kernelspec": {"language": "python"}}}\n',
    "docs/readme.rst": (
        "Bench Notes\n===========\n\nSee `the spec <spec.md>`_ and :ref:`setup`.\n\nSetup\n-----\n\n"
        ".. _setup:\n\n.. code-block:: matlab\n\n   run_all\n\n.. image:: bench.png\n   :alt: Bench\n\n"
        "- calibrate\n- run\n"
    ),
    "docs/howto.adoc": (
        "= How-to\n\n== Steps\n\nRun link:readme.rst[the notes] then <<results>>.\n\n[[results]]\n== Results\n\n"
        "[source,matlab]\n----\nplot_results\n----\n\ninclude::intro.tex[]\n"
    ),
    "docs/plan.org": (
        "#+TITLE: Plan\n\n* Goals\nSee [[file:spec.md][the spec]] and [[https://example.org/plan][site]].\n"
        "** Tasks\n- write\n- test\n#+BEGIN_SRC python\nx = 1\n#+END_SRC\n"
    ),
    "mail/thread.eml": (
        "From: a@example.org\r\nTo: b@example.org\r\nSubject: Bench results\r\n"
        "Date: Mon, 1 Jan 2024 10:00:00 +0000\r\nMIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="B"\r\n\r\n--B\r\nContent-Type: text/plain\r\n\r\n'
        "Results attached; see docs/spec.md.\r\n--B\r\nContent-Type: text/csv\r\n"
        'Content-Disposition: attachment; filename="table.csv"\r\n\r\na,b\r\n--B--\r\n'
    ),
    "data/settings.yaml": (
        "name: bench\npaths:\n  spec: docs/spec.md\n  site: https://example.org/y\nsteps:\n  - run: make\n"
    ),
    "data/tool.toml": '[project]\nname = "bench"\ndeps = ["pypdf>=5", "openpyxl"]\n[tool.x]\nlevel = 3\n',
    "data/build.xml": (
        '<?xml version="1.0"?>\n<project name="bench">\n'
        '  <target name="all" depends="docs/spec.md">Build</target>\n</project>\n'
    ),
    "data/app.ini": "[main]\nname = bench\ntable = data/table.csv\n",
    "requirements.txt": "pypdf>=5.0\nopenpyxl  # sheets\n",
    # Phase 3 session 2: container formats built in-process (see fixtures/office.py) and a
    # genuine legacy .doc that needs LibreOffice (recorded as unavailable under isolation).
    "docs/deck.pptx": office.PPTX,
    "docs/notes.odt": office.ODT,
    "docs/talk.odp": office.ODP,
    "docs/book.epub": office.EPUB,
    "docs/memo.rtf": office.RTF,
    "docs/legacy.doc": office.legacy_doc(),
    "bin/logo.gif": office.GIF,
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
