# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Allow `python -m contextmax`."""

import sys

from contextmax.cli import main

if __name__ == "__main__":
    sys.exit(main())
