# Phase 3 — Documents wave

Status: done 2026-09-17, released as `v0.3.0`. Builds on Phase 2 (`v0.2.0`).

## Goal

Every document format in the registry becomes readable through a dedicated adapter, with the
same `DocumentTree` contract Phase 1 defined, so outlines, references, text cache, links,
search and views work for PDFs, Office files, spreadsheets, notebooks and the rest exactly as
they do for Markdown. Documents also gain terms and concepts, named quantities, and
bibliography parsing, and citations resolve to BibTeX entries and project documents.

On the example archive: the thesis PDF and the other 18 PDFs get outlines from their bookmarks
(or derived headings), page-cited sections and parsed reference lists; the six workbooks become
searchable parameters with units and formulas; the presentations become readable; `cmx q term`
answers "what is GSKF" from the documents' own definitions.

## Deliverables

### 1. Text-based and structured formats (session 1)

- `pdf-v1` (pypdf, version-bound): text per page with page blocks, outline/bookmarks as the
  explicit table of contents (`toc_source: outline`) with page numbers, derived headings when
  there is no outline, link annotations, metadata title, encryption and scan detection
  (fewer than 60 characters per page on average flags `scan_detected`; no OCR).
- `bibtex-v1`: entries with key, type, title, authors, year, doi, url; each entry is a
  reference node with `ref_kind: bibentry`; citations anywhere in the project resolve to entries
  by key, and to a project document when the entry's title, DOI or file field matches one.
- `notebook-v1`: markdown cells become sections and paragraphs, code cells become code blocks
  and are also analysed by the code tiers using the kernel language, with `in_document: true`.
- `rst-v1`, `asciidoc-v1`, `org-v1`: headings, lists, code blocks, links and directives.
- `config-v1` (JSON, YAML, TOML, XML, INI, dependency manifests): keys and string values become
  searchable text; paths and URLs become references.
- `email-v1`: headers as metadata, subject as title, body paragraphs, attachments as references.
- An isolation switch (`CONTEXTMAX_NO_OPTIONAL_READERS`) so golden and determinism tests see
  every version-bound adapter as unavailable; reader tests skip when the package is absent.

### 2. Office and container formats (session 2)

- `ooxml-v1`: `.docx` paragraphs with heading styles as headings, tables row per line, hyperlinks,
  footnotes, comments, the TOC field when present; `.pptx` slides as sections with titles, body
  text and notes.
- `odf-v1`: `.odt`, `.odp`, `.odg` from `content.xml` with the same block model.
- `epub-v1`: chapters from the spine, each through the HTML adapter.
- `rtf-v1`: a small control-word parser for paragraphs and bold headings.
- `legacy-office-v1`: `.doc`, `.ppt`, `.xls` through LibreOffice headless when present, else
  Word COM on Windows, else catalog-only with the reason; determinism `environment-bound` with
  the converter version recorded.
- `image-v1`: dimensions and format from PNG, JPEG, GIF and BMP headers with the standard
  library; EXIF text through Pillow when installed; never OCR.
- Zip-bomb and size guards on every container; password-protected files recorded, never crashed.

### 3. Spreadsheets and parameters (session 3)

- `sheet-v1`: `.xlsx` (openpyxl, formulas and cached values), `.xls` (xlrd, values), `.ods`
  (OpenDocument XML), `.csv`/`.tsv` (stdlib). One record per populated cell: sheet, cell, label
  (nearest text cell to the left, then the column header), value, display, unit (from `[unit]`
  in the label or a neighbouring cell, normalised through a configurable alias table), formula,
  formula literals as their own unit-less rows, hidden flag. Bounded by
  `documents.sheet_max_rows` and `sheet_max_cols`; truncation announced.
- `nodes/parameters.jsonl`; prose quantities (number + unit from a configurable list, nearest
  preceding label) from every document; `cmx q param <label> [--compare] [--value N --unit U]`;
  `shares_parameter` edges between documents.

### 4. Terms, concepts and bibliographies (session 4)

- `docs/terms.py`: defined terms (`X (ABC)`, "X is defined as", glossary tables, definition
  lists, LaTeX acronym macros), acronyms with expansions, headings as topics, keyphrases by
  corpus TF-IDF over stopword-filtered n-grams with fixed rounding and explicit tie-breaks,
  capped per document with the cap announced. `nodes/terms.jsonl` with `method`, `defined_in`,
  `occurrences`; edges `defines` and `mentions_term`; `shares_term` between documents with
  generic-term suppression; `cmx q term`.
- Bibliography parsing from extracted text: a references section split into entries
  (`[n]`, `n.`, blank-line separated) with authors, year, title, DOI, URL; in-text citations
  `[12]`, `(Smith et al., 2020)` resolved to those entries; entries resolved to project
  documents by DOI, then title, then file stem.
- `docs.html` shows terms and parameters per document; `DOCMAP.md` lists terms and references;
  `INDEX.md` lists the most defined terms. Release `0.3.0`.

## Progress

### Session 1 — done 2026-09-17

Delivered every item of deliverable 1. Findings on the example archive (19 PDFs):

- pypdf yields one text line per printed line and no blank lines, so paragraphs are cut at
  headings, blank lines and short sentence-ending lines (under 70 % of the page's longest
  line); hyphenated line breaks are re-joined.
- Derived headings need four guards learned from the thesis: contents entries end with a page
  number (rejected), matrix rows start with a bare `0`/`1` (rejected unless the text is
  title-like), list-of-figures entries carry out-of-sequence numbers (a chapter counter carried
  across pages rejects `5.12` before chapter 1), and chapters print as `Chapter N` followed by
  the title on the next line (joined into one heading). Article-class documents number from
  `0.1`, so a zero major number is allowed when dotted.
- Titles: metadata first (rejecting file paths and "Microsoft Word - …" stamps), then the
  first line of page 1, then the first heading, then the file name; the source is recorded.
- pypdf logs warnings with Python object ids in them; they are captured per document, made
  deterministic and stored as notes, never printed.
- The `max_lines` limit counted raw bytes' newlines in PDFs and excluded the three largest
  references; container formats are now exempt.
- Two PDFs in the archive are 9-byte stubs; they are recorded as `extraction-failed`.
- Result: 17 of 19 PDFs read (one scan flagged), the thesis outline has 45 sections with page
  ranges (`Master_Thesis_VI_Kiriouchine.pdf p.33-59 §5`), 47 documents and 933 sections in
  total, artifact hash identical between a cached run and `--full`.

### Session 2 — done 2026-09-17

Delivered every item of deliverable 2, with a shared zip-guard module (`adapters/container.py`)
and synthetic fixtures (`tests/fixtures/office.py`) reused by the corpus. Findings:

- PowerPoint stores "Slide 1" as the document title and many decks have no title
  placeholder; titles that are only "Slide N" or a file path are rejected, and a slide's short
  first text line stands in (recorded as `title_source: first-text`).
- Sections in discrete units (slides, chapters) must not span into the next unit; the range
  closing rule now distinguishes shared pages from discrete pages.
- RTF hyperlinks live inside `{\*\fldinst …}` groups; ignorable destinations are skipped except
  field instructions, of which only `HYPERLINK` is read.
- LibreOffice 6.2 converts `.doc`/`.ppt` (and `.pot`) with `--convert-to docx|pptx`; the
  corpus carries a genuine 10 KB `.doc` produced that way so the "reader unavailable" path is
  in the goldens and the live path is tested where LibreOffice exists.
- Result on the example archive: the 71-slide graduation deck reads with slide cites
  (`…pptx slide 25 §attitude-estimation`), 247 images are catalogued with their dimensions,
  one PowerPoint template went through LibreOffice as environment-bound; 299 documents in total.

### Session 3 — done 2026-09-17

Delivered every item of deliverable 3 (`docs/units.py`, `docs/params.py`,
`docs/adapters/sheet.py`, `cmx q param`, `shares_parameter`). Findings:

- Unit aliases must be matched case-sensitively first: `Nm` is torque, `nm` is length, and a
  case-folded table silently turned one into the other.
- Prose labels: the phrase before a quantity, trimmed of edge stop words, restarted after the
  previous quantity (otherwise "deg at a sample rate" leaked the previous unit), never split at
  a colon ("torque limit: 1.5 Nm"), and never starting with table debris ("4 0 029"). Labels
  from PDF tables remain noisy; each carries its context and cite so an agent can check.
- The archive's six `KF_comparisons*.xlsx` workbooks have no left-hand labels: their column
  headers (`gskfo`, `ekf`, `kf`, `omega3` …) become the labels, recorded as `label_from:
  header`. Result: 648 cell parameters, 964 prose quantities, 43 `shares_parameter` edges.
- The compare verdict groups by the exact normalised label; "servo error" (two sheets) and
  "servo error stayed" (a report) are neighbours, not the same parameter, and both are shown.

### Session 4 — done 2026-09-17

Delivered deliverable 4 (`docs/terms.py`, `docs/bibliography.py`, `cmx q term`, term edges,
skill updates) and released `0.3.0`. Findings:

- An acronym regex that is greedy leftwards captures "The Extended Kalman Filter (EKF)"; the
  expansion is the **shortest** trailing phrase whose initials match, not the longest.
- Configuration files and spreadsheets were producing "topics" such as `main`, `paths` and
  `tool` from their keys, and keyphrases from `key = value` lines. Formats whose headings are
  keys contribute no terms at all; their content is already covered by parameters.
- Ranking matters as much as extraction: `q term EKF` first returned a u-blox register heading
  named `CFG-EKF`. Exact name, then exact acronym, then whole-word, then defined-over-statistical.
- PDF ligatures survive extraction as single code points, so "identiﬁcation" was unsearchable;
  the PDF adapter folds ligatures and smart quotes.
- Bibliography parsing on the real thesis: 31 entries with titles and years, 50 of 59 in-text
  citations resolved to them. Entries there resolve to no project document because the cited
  works are not in the archive, which is the honest result; the DOI and title paths are proven
  by the corpus test.
- Archive totals: 1487 terms (856 defined or headings), 909 references (460 resolved),
  1612 parameters, 3829 link edges including 2193 `mentions_term` and 110 `shares_term`.
- CI caught a determinism bug the local suite could not: the synthetic Office fixtures were
  DEFLATE-compressed, and this machine's Python links zlib-ng 1.3.1 while the runners link
  zlib 1.2.x. The same members compress to different bytes (`e2548c28` against `27bc69b5` in a
  direct comparison) and hash identically when stored, so every corpus file hash and every
  golden artifact depended on the builder. A second default hid behind it: `create_system` is
  0 on Windows and 3 on POSIX, which is why Windows kept passing while Linux and macOS failed
  on `data/params.ods`. Fixture packages are now stored with `create_system` pinned, and a
  determinism test refuses either default. Reading CI needed a detour: job logs require
  repository admin rights, so `scripts/golden_diff.py` names the first differing artifact, row,
  field and values, and CI puts that token into the artifact name, which the public API shows.

## Acceptance

Met, with the outcomes recorded as they happened rather than as they were assumed.

1. **Met.** Every corpus format yields a document with an outline or a recorded reason, and the
   isolation switch keeps the goldens identical whether or not the optional readers are
   installed. 190 tests.
2. **Met, with two corrections to the assumption.** 17 of the archive's 19 PDFs extract; the
   other two are 9-byte stubs and are recorded as `extraction-failed`, which is the honest
   result for a corrupt file. The thesis carries no bookmarks, so its 45 page-cited sections
   come from derived headings (`toc_source: derived`); four other PDFs do have bookmarks and
   use them. The six workbooks yield 648 cell parameters with units and formulas,
   `cmx q param --compare` reports agreement per label, and `cmx q term` answers from the
   documents' own definitions, for example `IMU = Inertial Measurement Unit`, defined at
   `Automatic_control_of_a_multirotor_nice_model.pdf p.59-61 §4.1` and occurring 73 times in
   three documents.
3. **Met.** Reader tests run in CI with `pypdf`, `openpyxl` and `xlrd` installed, and the
   cross-OS artifact hash is identical on Windows, Linux and macOS once the two zip defaults
   above were pinned.

## Risks and defaults

- PDF text order and hyphenation vary by producer: sections are derived from font-size heuristics
  only when there is no outline, and the derivation is labelled `toc_source: derived`.
- Legacy Office needs an external converter: environment-bound, recorded per document, and
  catalog-only when nothing is available.
- Keyphrases are statistical: never presented as "the concepts of the document", only as
  candidates with their score and method.
