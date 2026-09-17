# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Project configuration: defaults, schema, validation and the semantic hash.

The engine holds no domain vocabulary. Every name, pattern, cap and switch that describes a
project lives in `.contextmax/config.json`, validated here against a draft-07-style schema
subset implemented with the standard library so the base install needs no dependency.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contextmax.io.atomic import atomic_write_text
from contextmax.io.canon import sha256_json
from contextmax.version import SCHEMA_VERSION

SLUG_RE = r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$"

DEFAULT_ROLES: list[dict[str, str]] = [
    {
        "match": r"(^|/)(tests?|__tests__|testing|spec|specs)/|(^|/)test_[^/]*$|[._-]tests?\.[^/]+$|\.spec\.[^/]+$",
        "role": "test",
    },
    {
        "match": r"(^|/)(vendor|vendored|third[_-]?party|external|extern|node_modules)/",
        "role": "vendor",
    },
    {
        "match": r"(^|/)(generated|gen|autogen|__generated__)/|\.min\.(js|css)$|_pb2(_grpc)?\.py$|\.g\.(cs|py)$|\.designer\.cs$|\.(aux|lof|lot|toc|bbl|blg|out|fls|fdb_latexmk|synctex(\.gz)?|nav|snm)$",
        "role": "generated",
    },
    {"match": r"(^|/)(docs?|documentation|manuals?|papers?)/", "role": "docs"},
    {
        "match": r"(^|/)(\.github|\.gitlab|ci|build-scripts|scripts?|tools?)/|(^|/)(Makefile|CMakeLists\.txt|Dockerfile)$",
        "role": "build",
    },
]

DEFAULTS: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "project": {"slug": "project", "name": "Project", "description": "", "keywords": []},
    "roots": ["."],
    "output_dir": None,
    "respect_gitignore": True,
    "include": [],
    "exclude": [],
    "roles": DEFAULT_ROLES,
    "limits": {"max_file_mb": 64, "max_lines": 50000},
    "languages": {"overrides": {}, "disabled": []},
    "documents": {
        "sheet_max_rows": 400,
        "sheet_max_cols": 64,
        "stopwords_extra": [],
        "units_extra": [],
        "modal_words": ["shall", "must", "should", "is required to", "has to"],
        "id_patterns": [],
        "facets": {},
        "min_symbol_length": 4,
        "generic_term_share": 0.5,
        "max_owners": 40,
        "terms_cap": 40,
        "min_shared_terms": 3,
        "min_shared_parameters": 1,
        "max_shared_edges_per_doc": 12,
    },
    "graph": {"max_full_nodes": 5000, "max_cluster": 60},
    "viz": {"max_page_mb": 25},
    "skill": {"name": None, "hosts": ["claude-code-project"]},
    "mcp": {"enabled": True},
    "features": {"code": True, "documents": True, "links": True, "viz": True, "skill": True},
}

_RULE = {
    "type": "object",
    "required": ["match", "role"],
    "additionalProperties": False,
    "properties": {
        "match": {"type": "string", "minLength": 1},
        "role": {
            "type": "string",
            "enum": ["product", "test", "generated", "vendor", "docs", "build"],
        },
    },
}
_STRING_LIST = {"type": "array", "items": {"type": "string"}}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["schema_version", "project"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "project": {
            "type": "object",
            "required": ["slug"],
            "additionalProperties": False,
            "properties": {
                "slug": {"type": "string", "pattern": SLUG_RE},
                "name": {"type": "string"},
                "description": {"type": "string", "maxLength": 1000},
                "keywords": _STRING_LIST,
            },
        },
        "roots": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
        "output_dir": {"type": ["string", "null"]},
        "respect_gitignore": {"type": "boolean"},
        "include": _STRING_LIST,
        "exclude": _STRING_LIST,
        "roles": {"type": "array", "items": _RULE},
        "limits": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "max_file_mb": {"type": "number", "minimum": 0},
                "max_lines": {"type": "integer", "minimum": 0},
            },
        },
        "languages": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "overrides": {"type": "object", "additionalProperties": {"type": "string"}},
                "disabled": _STRING_LIST,
            },
        },
        "documents": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sheet_max_rows": {"type": "integer", "minimum": 1},
                "sheet_max_cols": {"type": "integer", "minimum": 1},
                "stopwords_extra": _STRING_LIST,
                "units_extra": _STRING_LIST,
                "modal_words": _STRING_LIST,
                "id_patterns": _STRING_LIST,
                "facets": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["match", "value"],
                            "additionalProperties": False,
                            "properties": {
                                "match": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        },
                    },
                },
                "min_symbol_length": {"type": "integer", "minimum": 1},
                "generic_term_share": {"type": "number", "minimum": 0, "maximum": 1},
                "max_owners": {"type": "integer", "minimum": 1},
                "terms_cap": {"type": "integer", "minimum": 1},
                "min_shared_terms": {"type": "integer", "minimum": 1},
                "min_shared_parameters": {"type": "integer", "minimum": 1},
                "max_shared_edges_per_doc": {"type": "integer", "minimum": 1},
            },
        },
        "graph": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "max_full_nodes": {"type": "integer", "minimum": 1},
                "max_cluster": {"type": "integer", "minimum": 2},
            },
        },
        "viz": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"max_page_mb": {"type": "number", "minimum": 1}},
        },
        "skill": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"name": {"type": ["string", "null"]}, "hosts": _STRING_LIST},
        },
        "mcp": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"enabled": {"type": "boolean"}},
        },
        "features": {
            "type": "object",
            "additionalProperties": False,
            "properties": {key: {"type": "boolean"} for key in DEFAULTS["features"]},
        },
    },
}

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _is_type(value: Any, name: str) -> bool:
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def schema_errors(data: Any, schema: dict[str, Any], path: str = "$", limit: int = 20) -> list[str]:
    """Validate `data` against a draft-07 subset; returns human-readable messages with paths."""
    errors: list[str] = []

    def walk(value: Any, node: dict[str, Any], where: str) -> None:
        if len(errors) >= limit:
            return
        if "const" in node and value != node["const"]:
            errors.append(f"{where}: expected {node['const']!r}, got {value!r}")
            return
        if "enum" in node and value not in node["enum"]:
            errors.append(f"{where}: {value!r} is not one of {node['enum']}")
            return
        if "type" in node:
            names = node["type"] if isinstance(node["type"], list) else [node["type"]]
            if not any(_is_type(value, name) for name in names):
                errors.append(f"{where}: expected {' or '.join(names)}, got {type(value).__name__}")
                return
        if isinstance(value, str):
            if "pattern" in node and not re.search(node["pattern"], value):
                errors.append(f"{where}: {value!r} does not match {node['pattern']}")
            if "minLength" in node and len(value) < node["minLength"]:
                errors.append(f"{where}: must be at least {node['minLength']} characters")
            if "maxLength" in node and len(value) > node["maxLength"]:
                errors.append(f"{where}: must be at most {node['maxLength']} characters")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in node and value < node["minimum"]:
                errors.append(f"{where}: must be >= {node['minimum']}")
            if "maximum" in node and value > node["maximum"]:
                errors.append(f"{where}: must be <= {node['maximum']}")
        if isinstance(value, dict):
            for key in node.get("required", []):
                if key not in value:
                    errors.append(f"{where}: missing required property '{key}'")
            props = node.get("properties", {})
            extra = node.get("additionalProperties", True)
            for key in sorted(value):
                child = f"{where}.{key}"
                if key in props:
                    walk(value[key], props[key], child)
                elif extra is False:
                    errors.append(f"{child}: unknown property")
                elif isinstance(extra, dict):
                    walk(value[key], extra, child)
        if isinstance(value, list):
            if "minItems" in node and len(value) < node["minItems"]:
                errors.append(f"{where}: needs at least {node['minItems']} item(s)")
            if "items" in node:
                for index, item in enumerate(value):
                    walk(item, node["items"], f"{where}[{index}]")

    walk(data, schema, path)
    return errors


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Fill every missing optional key from `base`, recursing into nested objects."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigError(ValueError):
    def __init__(self, messages: list[str], path: Path | None = None) -> None:
        self.messages = messages
        self.path = path
        where = f" in {path}" if path else ""
        super().__init__(f"invalid configuration{where}:\n  " + "\n  ".join(messages))


def extra_errors(data: dict[str, Any]) -> list[str]:
    """Checks the schema cannot express: regexes must compile."""
    errors: list[str] = []
    for index, rule in enumerate(data.get("roles", [])):
        try:
            re.compile(rule["match"])
        except re.error as exc:
            errors.append(f"$.roles[{index}].match: invalid regex ({exc})")
    for index, pattern in enumerate(data.get("documents", {}).get("id_patterns", [])):
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"$.documents.id_patterns[{index}]: invalid regex ({exc})")
    for facet, rules in data.get("documents", {}).get("facets", {}).items():
        for index, rule in enumerate(rules):
            try:
                re.compile(rule["match"])
            except re.error as exc:
                errors.append(f"$.documents.facets.{facet}[{index}].match: invalid regex ({exc})")
    return errors


@dataclass(frozen=True)
class RoleRule:
    regex: re.Pattern[str]
    role: str


class Config:
    """Validated configuration with defaults applied."""

    def __init__(self, data: dict[str, Any], path: Path | None = None) -> None:
        errors = schema_errors(data, SCHEMA)
        if not errors:
            errors = extra_errors(data)
        if errors:
            raise ConfigError(errors, path)
        self.raw: dict[str, Any] = copy.deepcopy(data)
        self.data: dict[str, Any] = deep_merge(DEFAULTS, data)
        self.path = path
        self._roles = tuple(RoleRule(re.compile(r["match"]), r["role"]) for r in self.data["roles"])

    # Convenience accessors ---------------------------------------------------------
    @property
    def slug(self) -> str:
        return self.data["project"]["slug"]

    @property
    def name(self) -> str:
        return self.data["project"].get("name") or self.slug

    @property
    def roots(self) -> list[str]:
        return list(self.data["roots"])

    @property
    def output_dir(self) -> str | None:
        return self.data.get("output_dir")

    @property
    def respect_gitignore(self) -> bool:
        return bool(self.data["respect_gitignore"])

    @property
    def include(self) -> list[str]:
        return list(self.data["include"])

    @property
    def exclude(self) -> list[str]:
        return list(self.data["exclude"])

    @property
    def max_file_bytes(self) -> int:
        return int(self.data["limits"]["max_file_mb"] * 1024 * 1024)

    @property
    def max_lines(self) -> int:
        return int(self.data["limits"]["max_lines"])

    @property
    def language_overrides(self) -> dict[str, str]:
        return dict(self.data["languages"]["overrides"])

    @property
    def disabled_languages(self) -> set[str]:
        return set(self.data["languages"]["disabled"])

    def feature(self, name: str) -> bool:
        return bool(self.data["features"].get(name, False))

    def role_for(self, key: str) -> str:
        for rule in self._roles:
            if rule.regex.search(key):
                return rule.role
        return "product"

    def semantic(self) -> dict[str, Any]:
        """The configuration with machine-local values removed, for the baseline identity."""
        data = copy.deepcopy(self.data)
        data.pop("output_dir", None)
        data["roots"] = [
            r if not Path(r).is_absolute() else f"<absolute:{Path(r).name}>" for r in data["roots"]
        ]
        return data

    def semantic_hash(self) -> str:
        return sha256_json(self.semantic())

    def full_hash(self) -> str:
        return sha256_json(self.data)


def default_config(slug: str, name: str | None = None, description: str = "") -> dict[str, Any]:
    """A minimal config for a new project; only non-default values are written."""
    return {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "slug": slug,
            "name": name or slug,
            "description": description,
            "keywords": [],
        },
        "roots": ["."],
        "output_dir": None,
        "respect_gitignore": True,
        "include": [],
        "exclude": [],
        "features": copy.deepcopy(DEFAULTS["features"]),
    }


def load_config(path: Path) -> Config:
    path = Path(path)
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError([f"not valid JSON: {exc}"], path) from exc
    if not isinstance(data, dict):
        raise ConfigError(["top level must be an object"], path)
    return Config(data, path)


def write_config(path: Path, data: dict[str, Any]) -> None:
    errors = schema_errors(data, SCHEMA) or extra_errors(data)
    if errors:
        raise ConfigError(errors, path)
    text = json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    atomic_write_text(Path(path), text)


def slugify(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:64].rstrip("-") or "project"


GITIGNORE_BLOCK = (
    "# ContextMAX: generated index is derived data; only the config is versioned\n"
    ".contextmax/*\n"
    "!.contextmax/config.json\n"
)
