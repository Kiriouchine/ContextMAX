# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Guards shared by every zip-based document format (OOXML, OpenDocument, EPUB).

A package is refused, with the reason recorded, when it is password protected, when one member
or the whole package would expand beyond fixed limits, or when a member's compression ratio is
extreme (zip bomb). XML members with entity declarations are refused as well."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

from contextmax.docs.base import ExtractionError

MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 768 * 1024 * 1024
MAX_RATIO = 200
RATIO_CHECK_FROM = 8 * 1024 * 1024


def open_package(data: bytes, what: str) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"not a valid {what} package: {exc}") from exc
    total = 0
    for info in zf.infolist():
        if info.flag_bits & 0x1:
            raise ExtractionError("password protected package")
        if info.file_size > MAX_MEMBER_BYTES:
            raise ExtractionError(
                f"member {info.filename} would expand to {info.file_size} bytes (zip bomb guard)"
            )
        ratio = info.file_size / max(info.compress_size, 1)
        if info.file_size > RATIO_CHECK_FROM and ratio > MAX_RATIO:
            raise ExtractionError(
                f"member {info.filename} has compression ratio {ratio:.0f} (zip bomb guard)"
            )
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise ExtractionError(f"package would expand beyond {MAX_TOTAL_BYTES} bytes (zip bomb guard)")
    return zf


def read_member(zf: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        return zf.read(name)
    except KeyError:
        return None
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ExtractionError(f"cannot read {name}: {exc.__class__.__name__}") from exc


def parse_xml(data: bytes, what: str) -> ET.Element:
    if b"<!ENTITY" in data[:50000]:
        raise ExtractionError(f"{what} declares XML entities; refused (safety)")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ExtractionError(f"{what} is not well-formed XML: {exc}") from exc


def read_xml(zf: zipfile.ZipFile, name: str) -> ET.Element | None:
    data = read_member(zf, name)
    if data is None:
        return None
    return parse_xml(data, name)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
