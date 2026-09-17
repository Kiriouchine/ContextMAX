# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`legacy-office-v1`: binary Word and PowerPoint files (.doc, .ppt) converted to OOXML by a
LibreOffice installation (`soffice --headless --convert-to`) and then read by `ooxml-v1`.
Environment-bound: the converter and its version are recorded on every document, and without a
converter the file is catalogued with that reason. Legacy spreadsheets go through `sheet-v1`."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from contextmax.docs.base import DocumentTree, ExtractionError

TARGETS = {".doc": "docx", ".dot": "docx", ".ppt": "pptx", ".pps": "pptx", ".pot": "pptx", ".wpd": "docx", ".wps": "docx"}
CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/snap/bin/libreoffice",
)
TIMEOUT_S = 180


@lru_cache(maxsize=1)
def find_converter() -> tuple[str, str] | None:
    """(soffice path, version string) or None."""
    if os.environ.get("CONTEXTMAX_NO_OPTIONAL_READERS"):
        return None
    path = shutil.which("soffice") or shutil.which("soffice.exe") or next((c for c in CANDIDATES if Path(c).is_file()), None)
    if not path:
        return None
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=60, check=False)
        version = (out.stdout or out.stderr).strip().split("\n")[0][:80] or "unknown version"
    except (OSError, subprocess.SubprocessError):
        version = "unknown version"
    return path, version


class LegacyOfficeAdapter:
    id = "legacy-office-v1"
    determinism = "environment-bound"

    @property
    def version(self) -> str:
        found = find_converter()
        return found[1] if found else "no converter"

    def available(self) -> tuple[bool, str]:
        if find_converter() is None:
            return False, "no converter found: install LibreOffice (soffice) to read legacy .doc/.ppt files"
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        found = find_converter()
        if found is None:
            raise ExtractionError("no converter found: install LibreOffice (soffice) to read legacy .doc/.ppt files")
        soffice, version = found
        ext = os.path.splitext(key)[1].lower()
        target = TARGETS.get(ext)
        if target is None:
            raise ExtractionError(f"no conversion target for {ext}")
        from contextmax.docs.adapters.ooxml import OoxmlAdapter

        with tempfile.TemporaryDirectory(prefix="contextmax-convert-") as tmp:
            src = Path(tmp) / f"input{ext}"
            src.write_bytes(data)
            try:
                proc = subprocess.run(
                    [soffice, "--headless", "--norestore", "--nologo", "--convert-to", target, "--outdir", tmp, str(src)],
                    capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
                    env={**os.environ, "HOME": tmp} if os.name != "nt" else None,
                )
            except subprocess.TimeoutExpired as exc:
                raise ExtractionError(f"LibreOffice conversion timed out after {TIMEOUT_S}s") from exc
            except OSError as exc:
                raise ExtractionError(f"LibreOffice could not be started: {exc.__class__.__name__}") from exc
            converted = Path(tmp) / f"input.{target}"
            if proc.returncode != 0 or not converted.is_file():
                detail = (proc.stderr or proc.stdout or "").strip().split("\n")[-1][:120]
                raise ExtractionError(f"LibreOffice conversion failed: {detail or 'no output file'}")
            tree = OoxmlAdapter().extract(key, converted.read_bytes())
        tree.adapter = self.id
        tree.adapter_version = version
        tree.determinism = self.determinism
        tree.metadata["converter"] = version
        tree.notes.append(f"converted from {ext} by {version}; text depends on the converter (environment-bound)")
        return tree
