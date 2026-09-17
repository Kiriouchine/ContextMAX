# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

from contextmax.registry import detect, formats, languages


def test_registries_are_consistent():
    seen: dict[str, str] = {}
    for fmt_id, fmt in formats().items():
        assert fmt["family"] in ("document", "data", "binary"), fmt_id
        assert fmt["determinism"] in (
            "intrinsic",
            "version-bound",
            "environment-bound",
            "catalog-only",
        )
        if fmt["adapter"] is None:
            assert fmt.get("reason"), f"{fmt_id} needs a reason when it has no adapter"
        for ext in fmt["extensions"]:
            assert ext.startswith(".") and ext == ext.lower(), ext
            assert ext not in seen, f"{ext} claimed by {seen[ext]} and {fmt_id}"
            seen[ext] = fmt_id
    for lang_id, lang in languages().items():
        for ext in lang["extensions"]:
            assert ext.startswith(".") and ext == ext.lower(), (lang_id, ext)
            assert ext not in seen, f"{ext} claimed by {seen[ext]} and {lang_id}"
            seen[ext] = lang_id


def test_detect_by_extension():
    d = detect("main.py", b"print(1)\n")
    assert (d.family, d.language, d.grammar, d.plugin, d.how) == (
        "code",
        "python",
        "python",
        "python",
        "extension",
    )
    d = detect("spec.PDF", b"%PDF-1.7")
    assert (d.family, d.format, d.adapter, d.determinism) == (
        "document",
        "pdf",
        "pdf-v1",
        "version-bound",
    )
    assert d.requires == ("pypdf",)


def test_detect_by_filename():
    assert detect("Makefile", b"all:\n").language == "make"
    assert detect("README", b"hello\n").format == "plain"
    assert detect("CMakeLists.txt", b"x").language == "cmake"
    assert detect("Dockerfile", b"FROM x").language == "dockerfile"


def test_detect_by_shebang():
    d = detect("noext", b"#!/usr/bin/env python3\nprint(1)\n")
    assert (d.language, d.how) == ("python", "shebang")
    d = detect("run", b"#!/bin/bash\necho\n")
    assert (d.language, d.how) == ("shell", "shebang")
    assert detect("script", b"#!/usr/bin/env -S node --harmony\n").language == "javascript"


def test_detect_by_sniff_and_fallback():
    assert detect("blob", b"\x00\x01\x02").family == "binary"
    assert detect("thing", b'{"a": 1}').format == "json"
    assert detect("thing", b"<?xml version='1.0'?><a/>").format == "xml"
    assert detect("thing", b"<!DOCTYPE html><html>").format == "html"
    d = detect("notes.zzz", b"free text\n")
    assert (d.family, d.format, d.adapter, d.how) == ("text", "plain", "plain-v1", "fallback")
    assert detect("archive.dat", b"PK\x03\x04rest").format == "archive"


def test_override_wins():
    d = detect("weird.dat", b"text", overrides={".dat": "python"})
    assert (d.language, d.how) == ("python", "override")
    d = detect("x.py", b"text", overrides={".py": "plain"})
    assert (d.format, d.how) == ("plain", "override")


def test_catalog_only_formats_carry_reason():
    d = detect("book.xlsb", b"\x00")
    assert d.adapter is None and d.determinism == "catalog-only" and d.reason
    d = detect("photo.png", b"\x89PNG")
    assert d.family == "binary" and d.adapter == "image-v1"
