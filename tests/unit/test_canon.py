# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

import unicodedata
from pathlib import Path

from contextmax.io.canon import canonical_json, join_key, parent_key, rel_key, sha256_json
from contextmax.io.jsonl import default_row_key, read_jsonl, write_json, write_jsonl


def test_rel_key_has_one_form():
    assert rel_key("a\\b\\c.txt") == "a/b/c.txt"
    assert rel_key("./a/b") == "a/b"
    assert rel_key("/a/b/") == "a/b"
    nfd = unicodedata.normalize("NFD", "ärm.md")
    assert rel_key(nfd) == unicodedata.normalize("NFC", "ärm.md")


def test_join_and_parent():
    assert join_key("", "x.py") == "x.py"
    assert join_key("a", "b", "c") == "a/b/c"
    assert parent_key("a/b/c") == "a/b"
    assert parent_key("c") == ""


def test_sha256_json_ignores_key_order_and_whitespace():
    a = {"b": 1, "a": [1, 2, {"z": "ü"}]}
    b = {"a": [1, 2, {"z": "ü"}], "b": 1}
    assert sha256_json(a) == sha256_json(b)
    assert canonical_json(a) == canonical_json(b)
    assert " " not in canonical_json(a)


def test_write_jsonl_sorts_rows_and_keys(tmp_path: Path):
    path = tmp_path / "rows.jsonl"
    rows = [{"id": "b", "z": 1, "a": 2}, {"id": "a", "k": 0}]
    digest = write_jsonl(path, rows)
    text = path.read_bytes()
    assert not text.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in text
    lines = text.decode("utf-8").splitlines()
    assert lines[0].startswith('{"id": "a"')
    assert lines[1] == '{"a": 2, "id": "b", "z": 1}'
    assert len(digest) == 64
    assert read_jsonl(path)[0]["id"] == "a"


def test_write_json_is_stable(tmp_path: Path):
    path = tmp_path / "x.json"
    first = write_json(path, {"b": [3, 1], "a": {"y": 1, "x": 2}})
    second = write_json(path, {"a": {"x": 2, "y": 1}, "b": [3, 1]})
    assert first == second


def test_default_row_key_orders_edges_after_nodes():
    node = {"id": "n"}
    edge = {"src": "a", "dst": "b", "rel": "calls"}
    assert default_row_key(node) < default_row_key(edge)
