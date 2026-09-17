# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Version and schema constants. Kept dependency-free so packaging can read it."""

__version__ = "0.1.0"

# Bumped whenever the shape of a generated artifact changes incompatibly.
SCHEMA_VERSION = 1

# Identifies the engine in manifests and adapter stamps.
ENGINE_ID = "contextmax"
