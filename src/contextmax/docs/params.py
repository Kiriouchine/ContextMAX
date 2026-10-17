"""Values with a name: one spelling per number and per unit, the numbers typed into a formula,
and the SQLite database that answers `contextmax params`.

A value is known by what it measures ("settle time"), not by its number: the same number
turns up everywhere, a label does not. The number then tells whether two documents agree.
"""
from __future__ import annotations

import decimal
import json
import os
import re
import sqlite3
from pathlib import Path

from contextmax import util

FORMAT_VERSION = 2          # 2: where each value is: its line, page, section, sentence, and where its name came from
# A range is written 1~4: a dash between two numbers reads as a minus, to a model as much as to a person.
RANGE_MARK = "~"
_RANGE_INPUT = re.compile("[~\u2013]")       # 4~20, and 4\u201320 as earlier versions wrote it

# Each unit with the spellings documents and workbooks use for it. A spelling is looked up as
# written, then lower-cased, except where case is the difference (newton-metre vs nanometre).
_SPELLINGS = (
    ("", ("n/a", "na", "n.a.", "[-]", "--", "-", "")),
    ("deg", ("deg", "degrees", "degree", "°")),
    ("um", ("µm", "μm")), ("us", ("µs", "μs")),
    ("uA", ("µa", "ua")), ("uV", ("µv", "uv")), ("uH", ("µh", "uh")),
    ("ohm", ("ω", "\N{OHM SIGN}", "ohm")),
    ("counts", ("count", "counts")), ("bits", ("bit", "bits")), ("bytes", ("byte", "bytes")),
    ("V", ("v",)), ("mV", ("mv",)), ("kV", ("kv",)), ("A", ("a",)), ("mA", ("ma",)),
    ("W", ("w",)), ("mW", ("mw",)), ("kW", ("kw",)),
    ("Hz", ("hz",)), ("kHz", ("khz",)), ("MHz", ("mhz",)), ("GHz", ("ghz",)),
    ("Pa", ("pa",)), ("kPa", ("kpa",)), ("MPa", ("MPa",)), ("mPa", ("mPa",)), ("dB", ("db",)),
    ("°C", ("°c",)), ("Nm", ("Nm",)), ("mNm", ("mNm", "mnm")), ("nm", ("nm",)),
    ("rpm", ("rpm",)), ("ppm", ("ppm",)), ("s", ("sec",)),
)
UNIT_OF = {spelling: unit for unit, spellings in _SPELLINGS for spelling in spellings}
CASE_MATTERS = frozenset({"Nm", "nm", "MPa", "mPa"})

_SPACES = re.compile(r"\s+")
_TRAILING_MARKS = re.compile(r"[.,;:=\s–\-]+$")
_QUOTED_TEXT = re.compile(r'"(?:[^"]|"")*"')               # a string in a formula; "" is a quote inside it
CELL_ADDRESS = re.compile(r"""
    (?: (?: [A-Za-z_][A-Za-z0-9_. ]* | '[^']+' ) ! )?      # sheet name, bare or quoted, then !
    [$]? [A-Z][A-Z]?[A-Z]? [$]? \d{1,7}                    # column letters, row number
""", re.VERBOSE)
_TYPED_NUMBER = re.compile(r"""
    (?<! [$._A-Za-z0-9] )                     # not the tail of a name, address or number
    [+-]? \d+ (?: [,.] \d+ )? (?: [eE] [+-]? \d+ )?
    (?! [._A-Za-z0-9] )
""", re.VERBOSE)

# Row labels found on every inspection form; they name nothing in particular.
_SAYS_NOTHING = frozenset("""
    a accept average b c comment comments count date fail id index item major max mean min minor
    n/a na no no. nok nr number ok pass qty quantity reject remarks result rev revision sum total
    typ unit units value x y yes z
""".split())


def _canon_piece(piece: str) -> str:
    """One number of a value: decimal comma or point, trailing zeros dropped, -0 is 0."""
    token = piece.strip().replace(",", ".")
    try:
        text = format(decimal.Decimal(token).normalize(), "f")
    except decimal.InvalidOperation:
        return token
    return text if text not in ("", "-0") else "0"


def canon_number(value) -> str:
    """One spelling per number, so 1, 1.0 and 1,0 meet; a range is written 4~20."""
    pieces = _RANGE_INPUT.split(str(value or "").strip())
    return RANGE_MARK.join(map(_canon_piece, pieces))


def canon_unit(unit) -> str:
    text = str(unit or "").strip()
    if text in UNIT_OF:
        return UNIT_OF[text]
    folded = text.lower()
    return UNIT_OF[folded] if folded in UNIT_OF and text not in CASE_MATTERS else text


def canon_label(label) -> str:
    """What the value measures: spacing and case folded, qualifiers such as 'nominal' kept."""
    spaced = _SPACES.sub(" ", str(label or "")).strip()
    return _TRAILING_MARKS.sub("", spaced).lower()


def _is_decimal(piece: str) -> bool:
    try:
        decimal.Decimal(piece.strip())
    except ArithmeticError:
        return False
    return True


def all_numbers(value) -> bool:
    return all(_is_decimal(p) for p in str(value or "").split(RANGE_MARK))


def says_nothing(label_norm: str) -> bool:
    return (not label_norm or len(label_norm) < 3 or label_norm in _SAYS_NOTHING
            or not re.search(r"[a-z]", label_norm))


def formula_constants(formula) -> list[str]:
    """Numbers typed into a formula, first appearance first. Quoted text and cell addresses
    are blanked before the search, so D5 or 'Sheet 2'!C7 never yield a number."""
    body = _QUOTED_TEXT.sub(" ", formula or "")
    body = CELL_ADDRESS.sub(lambda m: "R" + " " * (len(m.group(0)) - 1), body)
    found: dict[str, None] = {}
    for m in _TYPED_NUMBER.finditer(body):
        number = m.group(0)
        if number[0] in "+-" and _is_operator(number[0], body[:m.start()].rstrip()):
            number = number[1:]
        found.setdefault(number)
    return list(found)


def _is_operator(sign: str, before: str) -> bool:
    """A plus is never part of a typed number; a minus after a value or a bracket subtracts."""
    return sign == "+" or bool(before) and (before[-1].isalnum() or before[-1] in ")]%")


# Settings for a small, reproducible file; set before the first table is made.
_PRAGMAS = (("page_size", 4096), ("journal_mode", "OFF"), ("synchronous", "OFF"), ("temp_store", "MEMORY"),
            ("user_version", FORMAT_VERSION))
_TABLES = """
    CREATE TABLE sources (
        id INTEGER PRIMARY KEY, file_key TEXT NOT NULL UNIQUE, doc_ref TEXT NOT NULL,
        folder TEXT, relative_path TEXT, ext TEXT, doc_type TEXT, category TEXT, stage TEXT, module TEXT);
    CREATE TABLE places (
        id INTEGER PRIMARY KEY, source INTEGER NOT NULL REFERENCES sources(id),
        sheet TEXT, cell TEXT, label TEXT, label_norm TEXT NOT NULL, formula TEXT, hidden INTEGER NOT NULL,
        context TEXT, label_source TEXT, line_no INTEGER, page INTEGER, section TEXT, sentence TEXT, symbol TEXT);
    CREATE TABLE entries (
        id INTEGER PRIMARY KEY, place INTEGER NOT NULL REFERENCES places(id), origin TEXT NOT NULL,
        kind TEXT NOT NULL, value TEXT NOT NULL, value_as_written TEXT NOT NULL, value_shown TEXT NOT NULL,
        value_norm TEXT NOT NULL, value_exact_norm TEXT NOT NULL,
        unit TEXT NOT NULL, unit_as_written TEXT NOT NULL, unit_norm TEXT NOT NULL);
"""
_INDEXES = """
    CREATE INDEX ix_entries_value ON entries(value_norm, unit_norm);
    CREATE INDEX ix_entries_exact ON entries(value_exact_norm, unit_norm);
    CREATE INDEX ix_entries_origin ON entries(origin);
    CREATE INDEX ix_entries_place ON entries(place);
    CREATE INDEX ix_places_label ON places(label_norm);
    CREATE INDEX ix_places_source ON places(source);
    CREATE INDEX ix_sources_doc ON sources(doc_ref);
    ANALYZE;
"""
# Column -> key of a source record; doc_ref falls back to the file's own key.
_SOURCE_COLUMNS = {"file_key": "file_key", "doc_ref": "node_ref", "folder": "folder", "relative_path": "relative_path",
                   "ext": "ext", "doc_type": "kind", "category": "category", "stage": "stage", "module": "module"}
_PLACE_COLUMNS = ("source", "sheet", "cell", "label", "label_norm", "formula", "hidden", "context", "label_source",
                  "line_no", "page", "section", "sentence", "symbol")
_ENTRY_FIELDS = ("origin", "kind", "value", "value_as_written", "value_shown", "value_norm", "value_exact_norm",
                 "unit", "unit_as_written", "unit_norm")


def _insert(table: str, columns) -> str:
    columns = list(columns)
    return f"INSERT INTO {table}({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"


def _source_row(source: dict) -> list:
    row = [source.get(key) for key in _SOURCE_COLUMNS.values()]
    row[1] = row[1] or source["file_key"]
    return row


def _place_key(row: dict) -> tuple:
    """Rows of one document share a place when they come from the same cell (with the same
    label, formula and hidden flag) or, outside a workbook, from the same words on the same line."""
    in_cell = bool(row.get("sheet") and row.get("cell"))
    return (row.get("sheet"), row.get("cell"), row.get("label"), row.get("formula"), bool(row.get("hidden")),
            None if in_cell else (row.get("context"), row.get("line_no")))


def write_database(rows_path: Path, db_path: Path, sources: list[dict]) -> dict:
    """The value list as three tables (sources, places, entries) with an index per lookup.

    Built in a temporary file and moved into place when complete. The same rows in the same
    order give the same bytes, so the database counts towards the output fingerprint.
    """
    tmp = db_path.with_name(db_path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(str(tmp))
    try:
        for name, value in _PRAGMAS:
            con.execute(f"PRAGMA {name}={value}")
        con.executescript(_TABLES)
        source_id = {}
        for source in sorted(sources, key=lambda s: s["file_key"]):
            source_id[source["file_key"]] = con.execute(_insert("sources", _SOURCE_COLUMNS), _source_row(source)).lastrowid
        add_place, add_entry = _insert("places", _PLACE_COLUMNS), _insert("entries", ("place", *_ENTRY_FIELDS))
        entries = places = 0
        current_doc, place_of = None, {}
        for row in _rows(rows_path):
            if row["file_key"] != current_doc:
                current_doc, place_of = row["file_key"], {}
            key = _place_key(row)
            if key not in place_of:
                values = (source_id[current_doc], row.get("sheet"), row.get("cell"), row.get("label"),
                          row.get("label_norm") or "", row.get("formula"), int(bool(row.get("hidden"))), row.get("context"),
                          row.get("label_source"), row.get("line_no"), row.get("page"), row.get("section"),
                          row.get("sentence"), row.get("symbol"))
                place_of[key] = con.execute(add_place, values).lastrowid
                places += 1
            con.execute(add_entry, (place_of[key], *(row[field] for field in _ENTRY_FIELDS)))
            entries += 1
        con.executescript(_INDEXES)
        con.commit()
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()
    os.replace(tmp, db_path)
    return {"rows_count": entries, "sources_count": len(source_id), "places_count": places,
            "sha256": util.hash_file(db_path), "bytes": os.path.getsize(db_path)}


def _rows(path: Path):
    """The value rows one at a time: the file can be large."""
    with Path(path).open(encoding="utf-8") as fh:
        yield from (json.loads(line) for line in fh if not line.isspace())
