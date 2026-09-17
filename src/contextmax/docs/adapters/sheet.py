# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`sheet-v1`: spreadsheets as one `cell` block per populated cell (one line each in the text
cache) and one parameter record per value cell. Readers: .xlsx/.xlsm through openpyxl
(formulas and cached values), .xls through xlrd (values), .ods/.fods with the standard library,
.csv/.tsv with the csv module. Every sheet is a section; positions are sheet numbers
(`page_unit: sheet`) and rows.

Label heuristic: the nearest text cell to the left in the row, else the nearest text cell above
in the column (the header). Unit: `[unit]`/`(unit)` in the label, else a unit-like cell to the
right, else the header's unit. Numeric literals inside formulas become their own unit-less rows.
Bounds (`max_rows`, `max_cols`) are announced when hit."""

from __future__ import annotations

import csv
import datetime as dt
import io
import os
import re
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, ClassVar

from contextmax.docs.adapters.common import decode, squash
from contextmax.docs.adapters.container import local, open_package, parse_xml, read_xml
from contextmax.docs.base import Block, DocumentTree, ExtractionError
from contextmax.docs.params import norm_label
from contextmax.docs.units import alias_table, normalise_unit, split_label_unit, unit_like

LABEL_SCAN_LEFT = 8
HEADER_SCAN_UP = 40
FORMULA_LITERAL = re.compile(r"(?<![A-Za-z_$:!\d.])(-?\d+(?:\.\d+)?)(?![\d.]|\s*[:!])")
CELL_REF = re.compile(r"\$?[A-Z]{1,3}\$?\d+")
ODF_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
ODF_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


@dataclass
class Cell:
    value: Any  # number, bool, str, date or None
    formula: str | None = None
    kind: str = "text"  # text | number | bool | date | empty


@dataclass
class Sheet:
    name: str
    cells: dict[tuple[int, int], Cell] = field(default_factory=dict)  # (row, col) 1-based
    hidden: bool = False
    hidden_rows: set[int] = field(default_factory=set)
    hidden_cols: set[int] = field(default_factory=set)
    n_rows: int = 0
    n_cols: int = 0


def col_letter(col: int) -> str:
    out = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        out = chr(65 + rem) + out
    return out


def _package(name: str) -> bool:
    if os.environ.get("CONTEXTMAX_NO_OPTIONAL_READERS"):
        return False
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return squash(str(value))


def _classify(value: Any) -> Cell:
    if value is None or (isinstance(value, str) and not value.strip()):
        return Cell(None, kind="empty")
    if isinstance(value, bool):
        return Cell(value, kind="bool")
    if isinstance(value, (int, float)):
        return Cell(value, kind="number")
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return Cell(value.isoformat(), kind="date")
    text = str(value)
    if text.startswith("="):
        return Cell(None, formula=text, kind="number")
    return Cell(squash(text), kind="text")


def parse_number(text: str) -> int | float | None:
    """A CSV/ODS string that is a plain number ('2.0', '-3', '1e-3', '1,5' single-comma decimal)."""
    stripped = text.strip()
    if not re.fullmatch(r"[-+]?(?:\d+(?:[.,]\d+)?|\.\d+)(?:[eE][-+]?\d+)?%?", stripped):
        return None
    percent = stripped.endswith("%")
    cleaned = stripped.rstrip("%").replace(",", ".")
    value = float(cleaned)
    if percent:
        value /= 100.0
    if value.is_integer() and "." not in cleaned and "e" not in cleaned.lower() and not percent:
        return int(value)
    return value


class SheetAdapter:
    id = "sheet-v1"
    determinism = "version-bound"
    max_rows = 20000
    max_cols = 200
    units_extra: ClassVar[list[str]] = []  # replaced per project by the documents stage

    @property
    def version(self) -> str:
        parts = ["1"]
        for name in ("openpyxl", "xlrd"):
            if _package(name):
                parts.append(f"{name}-{metadata.version(name)}")
        return "+".join(parts)

    def available(self) -> tuple[bool, str]:
        return True, ""  # csv and ods never need a package; xlsx/xls are gated by `requires`

    # ----- entry ------------------------------------------------------------------------------
    def extract(self, key: str, data: bytes) -> DocumentTree:
        lower = key.lower()
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        if lower.endswith((".xlsx", ".xlsm", ".xltx", ".xltm")):
            sheets = self._read_xlsx(data, tree)
            tree.determinism = "version-bound"
        elif lower.endswith((".xls", ".xlt")):
            sheets = self._read_xls(data, tree)
            tree.determinism = "version-bound"
        elif lower.endswith((".ods", ".ots", ".fods")):
            sheets = self._read_ods(data)
            tree.determinism = "intrinsic"
        else:
            sheets = [self._read_csv(key, data)]
            tree.determinism = "intrinsic"
        tree.metadata["page_unit"] = "sheet"
        tree.metadata["line_unit"] = "row"
        tree.pages = len(sheets)
        tree.title = key.rsplit("/", 1)[-1]
        tree.metadata["title_source"] = "filename"
        table = alias_table(self.units_extra)
        n_params = 0
        for index, sheet in enumerate(sheets, start=1):
            tree.blocks.append(Block(kind="page", text=f"sheet {index}", page=index, line=1, end_line=1))
            tree.blocks.append(Block(kind="heading", text=sheet.name, level=1, page=index, line=1, end_line=1,
                                     extra={"hidden": sheet.hidden} if sheet.hidden else {}))
            if sheet.n_rows > self.max_rows or sheet.n_cols > self.max_cols:
                tree.notes.append(
                    f"TRUNCATED: sheet '{sheet.name}' has {sheet.n_rows} rows x {sheet.n_cols} columns; "
                    f"first {self.max_rows} rows x {self.max_cols} columns indexed"
                )
            n_params += self._emit(sheet, index, tree, table)
        tree.metadata["n_sheets"] = len(sheets)
        tree.metadata["n_parameters"] = n_params
        return tree

    # ----- cell records -----------------------------------------------------------------------
    def _emit(self, sheet: Sheet, index: int, tree: DocumentTree, table: dict[str, str]) -> int:
        cells = sheet.cells
        n_params = 0
        for (row, col) in sorted(cells):
            if row > self.max_rows or col > self.max_cols:
                continue
            cell = cells[(row, col)]
            coord = f"{col_letter(col)}{row}"
            if cell.kind == "empty":
                continue
            if cell.kind == "text":
                tree.blocks.append(Block(kind="cell", text=f"{coord}\t{cell.value}", page=index, line=row, end_line=row))
                continue
            label_raw, label_from = self._label(cells, row, col)
            header = self._header(cells, row, col)
            label, unit = split_label_unit(label_raw) if label_raw else ("", None)
            if not unit and header:
                _, unit = split_label_unit(header)
            if not unit:
                right = cells.get((row, col + 1))
                if right is not None and right.kind == "text" and unit_like(str(right.value), table):
                    unit = str(right.value).strip().strip("[]()")
            if not label:
                label = header or coord
                label_from = "header" if header else "coordinate"
            value = cell.value
            display = _display(value) if value is not None else (cell.formula or "")
            literals = self._literals(cell.formula) if cell.formula else []
            hidden = sheet.hidden or row in sheet.hidden_rows or col in sheet.hidden_cols
            record = {
                "sheet": sheet.name,
                "cell": coord,
                "row": row,
                "col": col,
                "label": label,
                "label_norm": norm_label(label),
                "label_from": label_from,
                "value": value,
                "display": display,
                "unit": unit,
                "unit_norm": normalise_unit(unit, table),
                "formula": cell.formula,
                "source_kind": "cell",
                "header": header,
                "hidden": hidden,
                "literals": literals,
            }
            line = f"{coord}\t{label}\t{display}\t{unit or ''}" + (f"\t{cell.formula}" if cell.formula else "")
            tree.blocks.append(Block(kind="cell", text=line, page=index, line=row, end_line=row, extra={"param": record}))
            n_params += 1
        return n_params

    @staticmethod
    def _label(cells: dict[tuple[int, int], Cell], row: int, col: int) -> tuple[str, str]:
        for c in range(col - 1, max(col - LABEL_SCAN_LEFT, 1) - 1, -1):
            left = cells.get((row, c))
            if left is not None and left.kind == "text" and left.value:
                if unit_like(str(left.value)):
                    continue  # a unit column between label and value
                return str(left.value), "left"
        return "", ""

    @staticmethod
    def _header(cells: dict[tuple[int, int], Cell], row: int, col: int) -> str | None:
        for r in range(row - 1, max(row - HEADER_SCAN_UP, 1) - 1, -1):
            above = cells.get((r, col))
            if above is not None and above.kind == "text" and above.value:
                return str(above.value)
        return None

    @staticmethod
    def _literals(formula: str) -> list[int | float]:
        body = CELL_REF.sub(" ", formula.lstrip("="))
        body = re.sub(r"'[^']*'|\"[^\"]*\"", " ", body)
        out: list[int | float] = []
        for m in FORMULA_LITERAL.finditer(body):
            text = m.group(1)
            out.append(float(text) if "." in text else int(text))
        return out

    # ----- readers ----------------------------------------------------------------------------
    def _read_xlsx(self, data: bytes, tree: DocumentTree) -> list[Sheet]:
        if not _package("openpyxl"):
            raise ExtractionError("openpyxl is not installed (pip install contextmax[office])")
        import warnings

        from openpyxl import load_workbook

        open_package(data, "Excel")  # zip guards
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                wb_f = load_workbook(io.BytesIO(data), data_only=False, read_only=False)
                wb_v = load_workbook(io.BytesIO(data), data_only=True, read_only=False)
        except Exception as exc:
            raise ExtractionError(f"unreadable workbook: {exc.__class__.__name__}: {squash(str(exc))[:100]}") from exc
        sheets: list[Sheet] = []
        for ws_f, ws_v in zip(wb_f.worksheets, wb_v.worksheets, strict=False):
            sheet = Sheet(name=ws_f.title, hidden=ws_f.sheet_state != "visible")
            sheet.n_rows, sheet.n_cols = ws_f.max_row or 0, ws_f.max_column or 0
            for key_, dim in ws_f.row_dimensions.items():
                if dim.hidden:
                    sheet.hidden_rows.add(int(key_))
            for _letter, dim in ws_f.column_dimensions.items():
                if dim.hidden and dim.min and dim.max:
                    sheet.hidden_cols.update(range(dim.min, dim.max + 1))
            for row_f in ws_f.iter_rows(min_row=1, max_row=min(sheet.n_rows, self.max_rows), max_col=min(sheet.n_cols, self.max_cols)):
                for c in row_f:
                    if c.value is None:
                        continue
                    cell = _classify(c.value)
                    if cell.formula:
                        cached = ws_v[c.coordinate].value
                        cell.value = cached if isinstance(cached, (int, float, bool)) else (squash(str(cached)) if cached is not None else None)
                        if isinstance(cached, str) and not isinstance(cell.value, (int, float)):
                            cell.kind = "number"  # keep as parameter: a formula whose cached value is text
                    sheet.cells[(c.row, c.column)] = cell
            sheets.append(sheet)
        wb_f.close()
        wb_v.close()
        return sheets

    def _read_xls(self, data: bytes, tree: DocumentTree) -> list[Sheet]:
        if not _package("xlrd"):
            raise ExtractionError("xlrd is not installed (pip install contextmax[office])")
        import xlrd

        try:
            book = xlrd.open_workbook(file_contents=data, on_demand=False)
        except Exception as exc:
            raise ExtractionError(f"unreadable workbook: {exc.__class__.__name__}: {squash(str(exc))[:100]}") from exc
        sheets: list[Sheet] = []
        for ws in book.sheets():
            sheet = Sheet(name=ws.name, hidden=ws.visibility != 0)
            sheet.n_rows, sheet.n_cols = ws.nrows, ws.ncols
            for r in range(min(ws.nrows, self.max_rows)):
                for c in range(min(ws.ncols, self.max_cols)):
                    ctype = ws.cell_type(r, c)
                    if ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        continue
                    raw = ws.cell_value(r, c)
                    if ctype == xlrd.XL_CELL_DATE:
                        try:
                            raw = xlrd.xldate_as_datetime(raw, book.datemode).isoformat()
                        except Exception:
                            raw = str(raw)
                        sheet.cells[(r + 1, c + 1)] = Cell(raw, kind="date")
                        continue
                    if ctype == xlrd.XL_CELL_BOOLEAN:
                        sheet.cells[(r + 1, c + 1)] = Cell(bool(raw), kind="bool")
                        continue
                    if ctype == xlrd.XL_CELL_NUMBER:
                        value = int(raw) if float(raw).is_integer() else raw
                        sheet.cells[(r + 1, c + 1)] = Cell(value, kind="number")
                        continue
                    if ctype == xlrd.XL_CELL_ERROR:
                        continue
                    sheet.cells[(r + 1, c + 1)] = _classify(raw)
            sheets.append(sheet)
        return sheets

    def _read_ods(self, data: bytes) -> list[Sheet]:
        if data.lstrip()[:1] == b"<":
            root = parse_xml(data, "flat OpenDocument spreadsheet")
        else:
            zf = open_package(data, "OpenDocument")
            root = read_xml(zf, "content.xml")
            if root is None:
                raise ExtractionError("content.xml missing")
        body = root.find(f"{ODF_OFFICE}body")
        ss = body.find(f"{ODF_OFFICE}spreadsheet") if body is not None else None
        if ss is None:
            raise ExtractionError("OpenDocument has no office:spreadsheet part")
        sheets: list[Sheet] = []
        for table in ss.findall(f"{ODF_TABLE}table"):
            sheet = Sheet(name=table.get(f"{ODF_TABLE}name") or f"Sheet{len(sheets) + 1}")
            row_no = 0
            for row in table.iter(f"{ODF_TABLE}table-row"):
                repeat_rows = int(row.get(f"{ODF_TABLE}number-rows-repeated") or 1)
                cells_in_row: list[tuple[int, Cell]] = []
                col_no = 0
                for cell_el in row:
                    if local(cell_el.tag) not in ("table-cell", "covered-table-cell"):
                        continue
                    repeat = int(cell_el.get(f"{ODF_TABLE}number-columns-repeated") or 1)
                    cell = self._ods_cell(cell_el)
                    if cell.kind != "empty" and repeat <= 50:
                        for k in range(repeat):
                            cells_in_row.append((col_no + k + 1, cell))
                    col_no += repeat
                if cells_in_row and repeat_rows <= 50:
                    for k in range(repeat_rows):
                        for col, cell in cells_in_row:
                            sheet.cells[(row_no + k + 1, col)] = cell
                            sheet.n_cols = max(sheet.n_cols, col)
                    sheet.n_rows = row_no + repeat_rows
                row_no += repeat_rows
            sheets.append(sheet)
        return sheets

    @staticmethod
    def _ods_cell(el: Any) -> Cell:
        vtype = el.get(f"{ODF_OFFICE}value-type")
        text = squash(" ".join("".join(p.itertext()) for p in el.iter(f"{ODF_TEXT}p")))
        formula = el.get(f"{ODF_TABLE}formula")
        if formula:
            formula = "=" + re.sub(r"\[\.?([A-Z]+\d+)\]", r"\1", formula.split(":=", 1)[-1] if ":=" in formula else formula.lstrip("="))
        if vtype in ("float", "percentage", "currency"):
            raw = el.get(f"{ODF_OFFICE}value")
            try:
                value = float(raw) if raw is not None else parse_number(text)
            except ValueError:
                value = parse_number(text)
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            return Cell(value, formula=formula, kind="number")
        if vtype == "boolean":
            return Cell(el.get(f"{ODF_OFFICE}boolean-value") == "true", formula=formula, kind="bool")
        if vtype in ("date", "time"):
            return Cell(el.get(f"{ODF_OFFICE}date-value") or el.get(f"{ODF_OFFICE}time-value") or text, kind="date")
        if not text:
            return Cell(None, kind="empty")
        if formula:
            return Cell(text, formula=formula, kind="number")
        return Cell(text, kind="text")

    def _read_csv(self, key: str, data: bytes) -> Sheet:
        text = decode(data)
        delimiter = "\t" if key.lower().endswith((".tsv", ".tab")) else ","
        sample = text[:4096]
        if delimiter == "," and sample.count(";") > sample.count(","):
            delimiter = ";"
        sheet = Sheet(name=key.rsplit("/", 1)[-1])
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        for r, row in enumerate(reader, start=1):
            if r > self.max_rows:
                sheet.n_rows = r
                continue
            for c, raw in enumerate(row, start=1):
                if c > self.max_cols:
                    continue
                if not raw.strip():
                    continue
                number = parse_number(raw)
                sheet.cells[(r, c)] = Cell(number, kind="number") if number is not None else Cell(squash(raw), kind="text")
                sheet.n_cols = max(sheet.n_cols, c)
            sheet.n_rows = max(sheet.n_rows, r)
        return sheet
