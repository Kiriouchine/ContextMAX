# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

import json
from pathlib import Path

import pytest

from contextmax.config import (
    DEFAULTS,
    SCHEMA,
    Config,
    ConfigError,
    default_config,
    load_config,
    schema_errors,
    slugify,
    write_config,
)


def test_default_config_validates_and_fills_defaults():
    cfg = Config(default_config("sample", "Sample"))
    assert cfg.slug == "sample"
    assert cfg.data["limits"]["max_file_mb"] == DEFAULTS["limits"]["max_file_mb"]
    assert cfg.data["documents"]["terms_cap"] == 40
    assert cfg.feature("code") is True
    assert cfg.roots == ["."]


def test_errors_carry_json_paths():
    data = default_config("Bad Slug")
    data["project"]["slug"] = "Bad Slug"
    data["limits"] = {"max_file_mb": -1, "unknown": 1}
    data["surprise"] = True
    errors = schema_errors(data, SCHEMA)
    joined = "\n".join(errors)
    assert "$.project.slug" in joined
    assert "$.limits.max_file_mb" in joined
    assert "$.limits.unknown: unknown property" in joined
    assert "$.surprise: unknown property" in joined


def test_bad_regex_is_reported():
    data = default_config("sample")
    data["roles"] = [{"match": "(unclosed", "role": "test"}]
    with pytest.raises(ConfigError) as info:
        Config(data)
    assert "$.roles[0].match" in str(info.value)


def test_role_rules_default_and_order():
    cfg = Config(default_config("sample"))
    assert cfg.role_for("src/app/main.py") == "product"
    assert cfg.role_for("tests/test_main.py") == "test"
    assert cfg.role_for("vendor/lib.py") == "vendor"
    assert cfg.role_for("docs/spec.md") == "docs"
    assert cfg.role_for("scripts/run.sh") == "build"
    assert cfg.role_for("gen/generated/x.py") == "generated"


def test_semantic_hash_ignores_machine_paths():
    a = default_config("sample")
    b = default_config("sample")
    b["output_dir"] = "D:/somewhere/else"
    assert Config(a).semantic_hash() == Config(b).semantic_hash()
    assert Config(a).full_hash() != Config(b).full_hash()


def test_load_and_write_roundtrip(tmp_path: Path):
    path = tmp_path / "config.json"
    write_config(path, default_config("sample", "Sample"))
    cfg = load_config(path)
    assert cfg.name == "Sample"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
    path.write_text(json.dumps({"schema_version": 99, "project": {"slug": "x"}}), encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert "$.schema_version" in str(info.value)


def test_bom_is_tolerated(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(default_config("sample")).encode("utf-8"))
    assert load_config(path).slug == "sample"


def test_slugify():
    assert slugify("My Project!") == "my-project"
    assert slugify("---") == "project"
    assert len(slugify("x" * 100)) <= 64
