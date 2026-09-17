# ADR-0005: Apache-2.0 and a permissive-only dependency policy

Status: accepted (2026-09-17)

## Context

ContextMAX is distributed as a product that people download and run, possibly inside companies.
The most capable PDF library for Python, PyMuPDF, is AGPL-3.0, which would impose obligations on
anyone redistributing a tool that depends on it.

## Decision

- ContextMAX is licensed under the Apache License 2.0; the copyright holder and author is
  Vsevolod Kiriouchine. Every source file carries `SPDX-License-Identifier: Apache-2.0`.
- Default and extra dependencies must be MIT, BSD, ISC or Apache-2.0 licensed.
- The default PDF adapter is `pypdf` (BSD). PyMuPDF is available only through the explicit
  `[mupdf]` extra, is excluded from `[all]`, and `contextmax doctor` labels it as AGPL when found.
- Any future dependency is recorded in `docs/how-it-works.md` with its license and what breaks
  without it.

## Consequences

- Users and companies can adopt and redistribute ContextMAX without copyleft obligations.
- PDF table extraction and layout analysis rely on permissive libraries (`pypdf`, optionally
  `pdfplumber`), accepting somewhat weaker results than PyMuPDF on difficult files; the
  determinism class and adapter version are recorded per document either way.
