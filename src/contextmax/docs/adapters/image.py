# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`image-v1`: images are catalogued, never OCR-ed. Dimensions and format come from the file
header with the standard library (PNG, JPEG, GIF, BMP, WebP); EXIF text fields
(description, artist, software, dates) are added when Pillow is installed. The document has
no body text; its notes say so."""

from __future__ import annotations

import io
import os
import struct
from importlib import metadata

from contextmax.docs.adapters.common import squash
from contextmax.docs.base import Block, DocumentTree, ExtractionError

EXIF_TAGS = {270: "description", 315: "artist", 305: "software", 306: "datetime", 0x9003: "datetime_original",
             0x9286: "user_comment"}


def dimensions(data: bytes) -> tuple[str, int, int] | None:
    """(format, width, height) from the header, or None when the format is not recognised."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        w, h = struct.unpack("<HH", data[6:10])
        return "gif", w, h
    if data[:2] == b"BM" and len(data) >= 26:
        w, h = struct.unpack("<ii", data[18:26])
        return "bmp", abs(w), abs(h)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return "webp", w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L" and len(data) >= 25:
            b0, b1, b2, b3 = data[21:25]
            return "webp", 1 + (((b1 & 0x3F) << 8) | b0), 1 + (((b3 & 0xF) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        if chunk == b"VP8X" and len(data) >= 30:
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return "webp", w, h
        return "webp", 0, 0
    if data[:2] == b"\xff\xd8":
        pos = 2
        n = len(data)
        while pos + 4 <= n:
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                pos += 2 if marker != 0xFF else 1
                continue
            if pos + 4 > n:
                break
            length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                if pos + 9 <= n:
                    h, w = struct.unpack(">HH", data[pos + 5 : pos + 9])
                    return "jpeg", w, h
                break
            if marker == 0xD9 or marker == 0xDA:
                break
            pos += 2 + length
        return "jpeg", 0, 0
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff", 0, 0
    if data[:4] == b"\x00\x00\x01\x00":
        return "ico", 0, 0
    return None


def _pillow_available() -> bool:
    if os.environ.get("CONTEXTMAX_NO_OPTIONAL_READERS"):
        return False
    try:
        metadata.version("Pillow")
    except metadata.PackageNotFoundError:
        return False
    return True


class ImageAdapter:
    id = "image-v1"
    determinism = "intrinsic"

    @property
    def version(self) -> str:
        return "1+pillow" if _pillow_available() else "1"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        info = dimensions(data)
        if info is None:
            raise ExtractionError("image header not recognised")
        fmt, width, height = info
        tree.title = key.rsplit("/", 1)[-1]
        tree.metadata.update({"image_format": fmt, "width": width, "height": height, "title_source": "filename"})
        tree.notes.append("image: no text extracted (no OCR); dimensions from the file header")
        if _pillow_available():
            try:
                from PIL import Image

                with Image.open(io.BytesIO(data)) as img:
                    exif = img.getexif()
                    fields: dict[str, str] = {}
                    for tag, name in EXIF_TAGS.items():
                        value = exif.get(tag)
                        if value is None:
                            try:
                                value = exif.get_ifd(0x8769).get(tag)
                            except Exception:
                                value = None
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", "replace")
                        if value and isinstance(value, str) and squash(value):
                            fields[name] = squash(value)[:300]
                    if fields:
                        tree.metadata["exif"] = dict(sorted(fields.items()))
                        tree.blocks.append(Block(kind="paragraph", text="; ".join(f"{k}: {v}" for k, v in sorted(fields.items())), line=1, end_line=1))
            except Exception as exc:
                tree.notes.append(f"EXIF not read ({exc.__class__.__name__})")
        return tree
