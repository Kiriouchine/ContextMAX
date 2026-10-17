"""Text recognition for scanned PDFs, page by page.

Pages are rendered with pypdfium2 at 300 dpi in grey: Windows' recognition drops decimal points in text
smaller than about 24 pixels, and 8-point print reaches that only from about 220 dpi. Two readers:
  - the recognition built into Windows (ps/ocr.ps1), first in the user's own language;
  - RapidOCR with its ONNX models, which setup.cmd installs, for PCs whose Windows has no recognition
    language, and for pages no Windows language reads.
One reader reads one script, and a page that is turned sideways reads as nothing or as nonsense. So a
page's text is kept only when it reads as words; otherwise the other languages and the other reader
are tried, then the page's orientation is found and every reader tries the page that way up. The most
word-like text wins, and each page records who read it.

Both readers give lines with their boxes and the slant of the text; layout() makes the page's text from
those: the slant taken out, a two-column page is read column by column, anything else row by row with
the cells of a row separated by tabs.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import unicodedata
import zlib
from dataclasses import dataclass, field
from pathlib import Path

OCR_VERSION = 2             # 2: language and rotation chosen per page, RapidOCR, rows and columns, 300 dpi
DPI = 300
MAX_SIDE = 8000             # pixels; Windows reads at most 10000 on a side, and a drawing at 300 dpi is larger
CHUNK_PAGES = 4             # pages recognised together: a long scan is shared out over the workers this way
WORDLIKE_ENOUGH = 0.8       # share of the text that reads as words, from which a page is kept without a second try
BLANK_INK = 0.002           # share of dark pixels below which a page with no text found is not tried again
INKED = 0.01                # a page this dark that gives fewer than SCANT_TEXT characters has not been read
SCANT_TEXT = 40
_STRIP = ".,;:!?()[]{}<>\"'«»„“”‘’–—-/\\|*•·…、。，：；！？「」『』（）"
_NOT_WORD = re.compile(r"[\W_]")
_UNITS = "°±%‰µΩ²³"
# units written with capitals inside: "mA", "kWh", "MHz" are words here, not a misread
_UNIT_WORDS = {p + u for p in ("", "k", "M", "G", "T", "m", "u", "n", "p")
               for u in ("A", "V", "W", "Wh", "VA", "VAr", "Hz", "Pa", "N", "Nm", "Ohm", "F", "H", "B", "J", "S", "T")}
_UNIT_WORDS |= {"dB", "dBm", "dBA", "dBi", "VDC", "VAC", "RPM", "IPxx", "mAh", "kVAr", "MPa", "GPa", "kN", "MN"}
_NUMBER = re.compile(r"[+\-±]?[\d.,:%°/x×]*\d[\d.,:%°/x×]*")
_EAST_ASIAN = ("CJK", "HIRAGANA", "KATAKANA", "HANGUL")      # one script group: Japanese mixes them
_TOKENS = re.compile(r"[\s、。，：；！？「」『』（）]+")         # East Asian text has punctuation, not spaces


def _script(ch: str) -> str:
    name = unicodedata.name(ch, "?")
    return "CJK" if name.startswith(_EAST_ASIAN) else name.split(" ")[0]


def _wordlike(token: str) -> bool:
    """A word, a number or a code, written in one script with ordinary capitals: "Pump", "PUMP",
    "4,5", "P-101", "m3/h", "°C", "Требования", "要求". Not "Tpe60BaHMA" or "nv•1TaHVIA", what one
    script's reader makes of another's."""
    token = token.strip(_UNITS)
    if not token or _NUMBER.fullmatch(token) or token in _UNIT_WORDS:
        return True
    if not all(c.isalnum() or c in "-_'’./" or unicodedata.category(c).startswith("M") for c in token):
        return False
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return True
    if len({_script(c) for c in letters}) != 1:
        return False
    cased = [c for c in letters if c.isupper() or c.islower()]      # Chinese, Arabic, Hebrew have no capitals
    return not cased or all(c.islower() for c in cased[1:]) or all(c.isupper() for c in cased)


def wordlike_share(text: str) -> tuple[float, int]:
    """The share of the text, in characters, that reads as words of two or more letters, as numbers or as
    East Asian characters, and the number of tokens. Lone letters count for nothing: a turned page reads
    as "o", "c", "d"."""
    tokens = [t.strip(_STRIP) for t in _TOKENS.split(text)]
    tokens = [t for t in tokens if t]
    total = sum(len(t) for t in tokens)
    if not total:
        return 0.0, 0
    good = sum(len(t) for t in tokens
               if (len(t) > 1 or t.isdigit() or _script(t) == "CJK") and _wordlike(t))
    return good / total, len(tokens)


@dataclass
class Line:
    left: float
    top: float
    width: float
    height: float
    text: str

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def middle(self) -> float:
        return self.top + self.height / 2


def _straightened(lines: list[Line], angle: float) -> list[Line]:
    """Lines moved up or down as if the page were not slanted by `angle` degrees (clockwise): on a
    slanted scan a table row's cells sit at different heights, and the next row's cell can be closer."""
    if abs(angle) < 0.2:
        return lines
    slope = math.tan(math.radians(angle))
    return [Line(ln.left, ln.top - (ln.left + ln.width / 2) * slope, ln.width, ln.height, ln.text) for ln in lines]


def _rows(lines: list[Line]) -> list[str]:
    """Lines whose middles lie within half a line height of their row's form that row, read left to right."""
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda ln: (ln.middle, ln.left)):
        last = rows[-1] if rows else None
        if last:
            middle = sum(ln.middle for ln in last) / len(last)
            if abs(middle - line.middle) < max(max(ln.height for ln in last), line.height) / 2:
                last.append(line)
                continue
        rows.append([line])
    return ["\t".join(ln.text for ln in sorted(row, key=lambda ln: ln.left)) for row in rows]


def _gutter(lines: list[Line], width: float) -> float | None:
    """The x of the gap between two columns of prose, or None. Tables have short cells and stay rows;
    a title or a figure across both columns may cross the gap."""
    if len(lines) < 8 or width <= 0:
        return None
    best = None
    for step in range(70, 131):
        x = width * step / 200                         # 35% to 65% of the page width
        crossing = sum(1 for ln in lines if ln.left < x < ln.right)
        if best is None or crossing < best[1]:
            best = (x, crossing)
    x, crossing = best
    left = [ln for ln in lines if ln.right <= x]
    right = [ln for ln in lines if ln.left >= x]
    if crossing > 0.1 * len(lines) or min(len(left), len(right)) < 4:
        return None

    def median_width(group):
        return sorted(ln.width for ln in group)[len(group) // 2]

    if min(median_width(left), median_width(right)) < 0.25 * width:
        return None
    return x


def layout(lines: list[Line], width: float, angle: float = 0.0) -> str:
    """The page's text: the slant taken out, two columns of prose column by column (a line across both
    columns stays in its place), everything else row by row."""
    lines = _straightened(lines, angle)
    x = _gutter(lines, width)
    if x is None:
        return "\n".join(_rows(lines))
    out, band = [], []

    def flush():
        out.extend(_rows([ln for ln in band if ln.right <= x]))
        out.extend(_rows([ln for ln in band if ln.left >= x]))
        band.clear()

    for line in sorted(lines, key=lambda ln: ln.top):
        if line.left < x < line.right:                 # across the gap: a title, a caption
            flush()
            out.append(line.text)
        else:
            band.append(line)
    flush()
    return "\n".join(out)


def _lying(lines: list[Line]) -> float:
    """How much of the page is text lines lying flat, in pixels of line length, whatever they read as:
    a page the right way up has long flat lines, a page on its side has standing ones or none."""
    return sum(ln.width for ln in lines if ln.width >= 2 * ln.height)


@dataclass
class PageText:
    text: str = ""
    reader: str = ""            # "windows en-GB", "rapidocr cyrillic", ...
    rotation: int = 0
    share: float = 0.0          # how much of it reads as words
    chars: int = 0

    @property
    def score(self) -> float:
        """Plausible text, weighed strongly by how plausible: three junk words do not beat a page of
        Chinese, and a long half-sense reading does not beat the right one."""
        return self.share * self.share * self.chars

    def better_than(self, other: PageText) -> bool:
        return (round(self.score, 1), self.share) > (round(other.score, 1), other.share)


@dataclass
class Outcome:
    ok: bool
    text: str = ""
    error: str = ""
    pages: int = 0               # pages rendered and read
    page_count: int = 0          # pages in the file
    readers: dict = field(default_factory=dict)      # reader -> pages it read
    turned: int = 0              # pages read turned
    empty: int = 0               # pages with no text
    doubtful: int = 0            # pages whose best text still does not read as words
    problems: list = field(default_factory=list)     # what went wrong on the way, for the record
    page_lines: list | None = None                   # the line each page starts on, in `text`


def _png_grey(width: int, height: int, stride: int, buf: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + tag + data + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big")
    raw = b"".join(b"\x00" + buf[y * stride:y * stride + width] for y in range(height))
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 0, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")


_DARK = bytes(range(160))


def render(pdf_path: str, out_dir: Path, pages: list[int] | None = None, rotation: int = 0) -> tuple[dict, int]:
    """page-0001.png ... in grey; returns ({page number: share of dark pixels}, pages in the file).
    `pages` are 0-based page indexes; by default every page."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    from contextmax.docs.readers import win_path

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(win_path(pdf_path))
    ink = {}
    try:
        count = len(doc)
        for i in pages if pages is not None else range(count):
            page = doc[i]
            try:
                w, h = page.get_size()
                scale = min(DPI / 72, MAX_SIDE / max(w, h, 1))
                bitmap = page.render(scale=scale, rotation=rotation, grayscale=True,
                                     force_bitmap_format=pdfium_c.FPDFBitmap_Gray)
                try:
                    buf = bytes(bitmap.buffer)
                    sample = buf[::61]
                    ink[i + 1] = (len(sample) - len(sample.translate(None, _DARK))) / max(len(sample), 1)
                    (out_dir / f"page-{i + 1:04d}.png").write_bytes(
                        _png_grey(bitmap.width, bitmap.height, bitmap.stride, buf))
                finally:
                    bitmap.close()
            finally:
                page.close()
    finally:
        doc.close()
    return ink, count


def _page_number(name: str) -> int:
    return int(re.search(r"(\d+)", name).group(1))


# ---- the readers -------------------------------------------------------------------------------------

# RapidOCR's own model (in its wheel) reads Latin script (47 languages), Chinese and Japanese, but no
# Cyrillic. The Cyrillic model (Russian, Ukrainian, Bulgarian, Serbian and more, with Latin) is fetched
# by `contextmax ocr-models` when setup.cmd runs, never while ContextMAX reads, and checked by SHA-256.
RAPID_MODELS = {
    "cyrillic": ("cyrillic_PP-OCRv5_rec_mobile.onnx", "90f761b4bfcce0c8c561c0cb5c887b0971d3ec01c32164bdf7374a35b0982711"),
}
RAPID_URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/{name}"
_RAPID: dict = {}
_MODEL_OK: dict = {}


def models_dir() -> Path:
    """Inside the private environment, so it goes with it; CONTEXTMAX_OCR_MODELS points elsewhere."""
    import sys

    return Path(os.environ.get("CONTEXTMAX_OCR_MODELS") or Path(sys.prefix) / "contextmax-models")


def _model_ok(path: Path, sha256: str) -> bool:
    """The file is there and is the one its SHA-256 names (checked once per run)."""
    from contextmax import util

    key = str(path)
    if key not in _MODEL_OK:
        _MODEL_OK[key] = path.is_file() and util.hash_file(path) == sha256
    return _MODEL_OK[key]


def fetch_models(target: Path | None = None, source: Path | None = None) -> list[str]:
    """Put RAPID_MODELS in `target` (default: models_dir()), copied from `source` (an offline installer's
    wheels\\models) or downloaded with curl, which trusts the certificates Windows trusts (Python's own
    list does not know an antivirus or company proxy that inspects HTTPS). A file is kept only when its
    SHA-256 matches, and a file there that does not match is removed. Returns one line per model;
    raises OSError when one could not be had."""
    import subprocess

    from contextmax import util

    target = target or models_dir()
    target.mkdir(parents=True, exist_ok=True)
    done, failed = [], []
    for model, (name, sha256) in RAPID_MODELS.items():
        final = target / name
        _MODEL_OK.pop(str(final), None)
        if final.is_file():
            if util.hash_file(final) == sha256:
                done.append(f"{model} model: already there")
                continue
            final.unlink()                      # never left to be used: it is not the model it claims to be
        partial = final.with_name(name + ".partial")
        try:
            if source:
                shutil.copyfile(source / name, partial)
            else:
                r = subprocess.run(["curl.exe", "-fsSL", "--retry", "2", "--connect-timeout", "20", "-y", "60",
                                    "-Y", "1024", "-o", str(partial), RAPID_URL.format(name=name)],
                                   capture_output=True, text=True, timeout=1800,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if r.returncode:
                    raise OSError(f"download failed ({(r.stderr or '').strip() or r.returncode})")
        except (OSError, subprocess.TimeoutExpired) as exc:
            partial.unlink(missing_ok=True)
            failed.append(f"{model} model: {exc}")
            continue
        if util.hash_file(partial) != sha256:
            partial.unlink()
            failed.append(f"{model} model: the file does not match its SHA-256, so it is not used")
            continue
        os.replace(partial, final)
        done.append(f"{model} model: {'copied' if source else 'downloaded'} ({final.stat().st_size / 1e6:.0f} MB)")
    if failed:
        raise OSError("; ".join(done + failed))
    return done


_RAPID_PROBLEM: list[str] = []


def _quiet_onnxruntime() -> None:
    """ONNX Runtime's own usage events off, as far as it allows: what it records when it is imported,
    and anything Windows' diagnostic data collects, only Windows' own settings decide."""
    import onnxruntime

    if hasattr(onnxruntime, "disable_telemetry_events"):
        onnxruntime.disable_telemetry_events()


def rapid_problem() -> str:
    """Why RapidOCR cannot read on this PC, or "" when it can. Asked once."""
    if not _RAPID_PROBLEM:
        try:
            import rapidocr  # noqa: F401

            _quiet_onnxruntime()
            _RAPID_PROBLEM.append("")
        except ImportError as exc:
            if "DLL load failed" in str(exc):
                _RAPID_PROBLEM.append("RapidOCR cannot start: Windows lacks the Microsoft Visual C++ 2015-2022 "
                                      "runtime (vc_redist.x64.exe from Microsoft; installing it needs an administrator)")
            else:
                _RAPID_PROBLEM.append(f"RapidOCR is not installed ({exc}); run setup.cmd again")
        except OSError as exc:
            _RAPID_PROBLEM.append(f"RapidOCR cannot start: {exc}")
    return _RAPID_PROBLEM[0]


def rapid_models() -> list[str]:
    """The RapidOCR models this PC can use: its own first, then Cyrillic when fetched and intact."""
    if rapid_problem():
        return []
    return ["default"] + [m for m, (name, sha) in RAPID_MODELS.items() if _model_ok(models_dir() / name, sha)]


def _rapid_engine(model: str):
    if model not in _RAPID:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        params = {"Global.log_level": "error", "Global.max_side_len": 3600, "Global.text_score": 0.3,
                  "Det.box_thresh": 0.4}
        from contextmax import parallel

        if parallel.in_worker():
            # several scans at once, each in its own worker: each worker its share of the processors. The
            # text is the same with any number of threads (measured on the pages of real scans)
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = parallel.threads_per_worker()
        if model != "default":
            params.update({"Rec.model_path": str(models_dir() / RAPID_MODELS[model][0]),
                           "Rec.lang_type": getattr(LangRec, model.upper()), "Rec.ocr_version": OCRVersion.PPOCRV5,
                           "Rec.model_type": ModelType.MOBILE})
        _quiet_onnxruntime()
        _RAPID[model] = RapidOCR(params=params)
    return _RAPID[model]


def _slant(boxes) -> float:
    """The page's slant in degrees, clockwise, from the top edges of RapidOCR's long line boxes."""
    angles = sorted(math.degrees(math.atan2(b[1][1] - b[0][1], b[1][0] - b[0][0])) for b in boxes
                    if abs(b[1][0] - b[0][0]) > 3 * abs(b[3][1] - b[0][1]) > 0)
    return angles[len(angles) // 2] if angles else 0.0


def _read_rapid(folder: Path, model: str) -> dict:
    """{page number: (lines, width, slant, error)} for the pages in `folder`."""
    pages = sorted(folder.glob("page-*.png"))
    try:
        import numpy as np
        from PIL import Image

        engine = _rapid_engine(model)
    except Exception as exc:  # noqa: BLE001 - every page of this run gets the reason
        return {_page_number(p.name): ([], 0.0, 0.0, f"RapidOCR {model}: {type(exc).__name__}: {exc}") for p in pages}
    out = {}
    for png in pages:
        n = _page_number(png.name)
        try:
            with Image.open(png) as im:
                rgb = np.asarray(im.convert("RGB"))
            result = engine(rgb)
            boxes = [[(float(x), float(y)) for x, y in box] for box in (result.boxes if result.boxes is not None else [])]
            lines = []
            for box, txt in zip(boxes, result.txts or [], strict=True):
                xs, ys = [p[0] for p in box], [p[1] for p in box]
                lines.append(Line(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), txt))
            out[n] = (lines, float(rgb.shape[1]), _slant(boxes), "")
        except Exception as exc:  # noqa: BLE001 - one page's failure is that page's reason
            out[n] = ([], 0.0, 0.0, f"{type(exc).__name__}: {exc}")
    return out


def _read_windows(folder: Path, language: str | None, timeout: int) -> tuple[dict, str, str]:
    """({page number: (lines, width, slant, error)}, the language used, an error for the whole run)."""
    from contextmax import office

    args = ["-Pages", str(folder)] + (["-Language", language] if language else [])
    ok, stdout, err = office.run_script("ocr.ps1", args, timeout)
    if not ok:
        return {}, language or "", err or "Windows text recognition failed"
    out, used = {}, language or ""
    for raw in stdout.splitlines():
        if not raw.startswith("{"):
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        used = d.get("language") or used
        lines = [Line(float(x), float(y), float(w), float(h), str(t)) for x, y, w, h, t in d.get("lines") or []]
        # Windows gives the boxes as if the page were straight ("when TextAngle is 0"): no slant to take out
        out[_page_number(d["page"])] = (lines, float(d.get("width") or 0), 0.0, d.get("error") or "")
    return out, used, ""


def _subset(folder: Path, numbers: list[int], name: str) -> Path:
    """A folder with only these pages' images (linked, not copied, where the disk allows)."""
    sub = folder.parent / name
    sub.mkdir(exist_ok=True)
    for n in numbers:
        src, dst = folder / f"page-{n:04d}.png", sub / f"page-{n:04d}.png"
        if dst.exists():
            continue
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
    return sub


def _not_read(page: PageText, ink: float) -> bool:
    if not page.text.strip() and ink < BLANK_INK:
        return False                            # an empty page
    return page.share < WORDLIKE_ENOUGH or (ink >= INKED and page.chars < SCANT_TEXT)


def page_png(pdf_path: str, index: int, dpi: int = 150, max_side: int = 1800) -> bytes:
    """One page (counted from 0) as a grey PNG, for a model that reads pictures: enough to read print, small
    enough to send."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    from contextmax.docs.readers import win_path

    doc = pdfium.PdfDocument(win_path(pdf_path))
    try:
        page = doc[index]
        try:
            w, h = page.get_size()
            bitmap = page.render(scale=min(dpi / 72, max_side / max(w, h, 1)), grayscale=True,
                                 force_bitmap_format=pdfium_c.FPDFBitmap_Gray)
            try:
                return _png_grey(bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer))
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        doc.close()


def page_count(pdf_path: str) -> int:
    import pypdfium2 as pdfium

    from contextmax.docs.readers import win_path

    doc = pdfium.PdfDocument(win_path(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


def chunks(count: int) -> list[tuple[int, int]]:
    """The pages of a scan as (first, last) pieces of CHUNK_PAGES, counted from 0; the same pieces however
    many workers read them, so the result never depends on how many there are."""
    return [(a, min(a + CHUNK_PAGES, count)) for a in range(0, count, CHUNK_PAGES)]


def read_pdf(pdf_path: str, windows_languages: list[str] | None = None) -> Outcome:
    """Recognise the text of a scanned PDF, every page of it, a few pages at a time (read_pages), here.
    `windows_languages`: what Windows can read on this PC (the probe's list); empty when Windows has no
    recognition. Never raises: what goes wrong is the outcome's."""
    if not windows_languages and not rapid_models():
        return Outcome(False, error="no text recognition on this PC (no Windows recognition language, no RapidOCR)")
    try:
        count = page_count(pdf_path)
    except Exception as exc:  # noqa: BLE001 - reported as this file's reason
        return Outcome(False, error=f"cannot render pages: {type(exc).__name__}: {exc}")
    return merge([read_pages(pdf_path, a, b, windows_languages) for a, b in chunks(count)])


def read_pages(pdf_path: str, first: int, last: int, windows_languages: list[str] | None = None) -> dict:
    """The pages first..last-1 (counted from 0) of a scanned PDF, recognised. A page's text depends on that
    page alone, so a scan read in pieces, by several workers or one, reads as it would in one go. Returns
    the piece merge() puts together with the others. Never raises."""
    windows_languages = list(windows_languages or [])
    rapid = rapid_models()
    if not windows_languages and not rapid:
        return {"fatal": "no text recognition on this PC (no Windows recognition language, no RapidOCR)"}
    # every reader, in the order they are asked: Windows in the user's language, Windows' other
    # languages, then RapidOCR's models. None as the language is the user's own.
    readers = ([("windows", None)] + [("windows", lang) for lang in windows_languages] if windows_languages else [])
    readers += [("rapidocr", model) for model in rapid]
    with tempfile.TemporaryDirectory(prefix="cmx-ocr-", ignore_cleanup_errors=True) as tmp:
        pages_dir = Path(tmp) / "pages"
        try:
            ink, count = render(pdf_path, pages_dir, list(range(first, last)))
        except Exception as exc:  # noqa: BLE001 - reported as this file's reason
            return {"fatal": f"cannot render pages: {type(exc).__name__}: {exc}"}
        if not ink:
            return {"best": {}, "ink": {}, "problems": [], "count": count}
        best = {n: PageText() for n in ink}
        lying = {n: {} for n in ink}            # page -> {rotation: flat line length the first reader saw}
        timeout = 120 + 10 * len(ink)
        problems: list[str] = []
        tried_language: set = set()

        def run(reader, folder: Path, rotation: int = 0) -> None:
            kind, which = reader
            try:
                if kind == "windows":
                    if which is not None and which.lower() in tried_language:
                        return                  # the user's own language, read as the first reader
                    results, used, error = _read_windows(folder, which, timeout)
                    if error:
                        problems.append(error)
                    if which is None and not rotation:
                        tried_language.add(used.lower())
                    name = f"windows {used}"
                else:
                    results, name = _read_rapid(folder, which), f"rapidocr {which}"
            except Exception as exc:  # noqa: BLE001 - a reader that breaks is a reason, not a stop
                problems.append(f"{kind} {which or ''}: {type(exc).__name__}: {exc}")
                return
            for n, (lines, width, slant, error) in results.items():
                if error:
                    problems.append(f"page {n}: {error}")
                    continue
                if reader == readers[0]:
                    lying[n][rotation] = _lying(lines)
                text = layout(lines, width, slant)
                share, _ = wordlike_share(text)
                # lines standing on end are a page turned on the scanner, however well they read
                chars = sum(len(ln.text) for ln in lines) or 1
                share *= 1 - sum(len(ln.text) for ln in lines if ln.height > 1.5 * ln.width) / chars
                # lines found on the page that read as (almost) nothing: a script this reader cannot read
                widths = sum(ln.width for ln in lines) or 1
                share *= 1 - sum(ln.width for ln in lines if len(_NOT_WORD.sub("", ln.text)) < 2) / widths
                candidate = PageText(text, name, rotation, share, len(_NOT_WORD.sub("", text)))
                if candidate.better_than(best[n]):
                    best[n] = candidate

        def unread() -> list[int]:
            """Pages whose text does not read as words yet, or that are dark with ink and gave almost no
            text; a page with almost no ink and no text is empty."""
            return [n for n, p in best.items() if _not_read(p, ink[n])]

        def turned_folder(rotation: int, numbers: list[int]) -> Path | None:
            folder = Path(tmp) / f"turned-{rotation}"
            missing = [n for n in numbers if not (folder / f"page-{n:04d}.png").exists()]
            try:
                if missing:
                    render(pdf_path, folder, [n - 1 for n in missing], rotation)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"cannot render turned pages: {type(exc).__name__}: {exc}")
                return None
            return _subset(folder, numbers, f"turned-{rotation}-{len(numbers)}-{numbers[0]}")

        # 1. upright: the first reader reads every page, each next reader the pages still unread
        run(readers[0], pages_dir)
        for reader in readers[1:]:
            todo = unread()
            if not todo:
                break
            run(reader, _subset(pages_dir, todo, f"{reader[0]}-{reader[1]}"))
        # 2. pages turned on the scanner: the first reader looks at each still unread page turned a
        #    quarter, three quarters and half a turn; the way up with the longest flat lines is the
        #    page's, and there every other reader tries it too (a turned page in another script)
        for rotation in (90, 270, 180):
            todo = unread()
            if not todo:
                break
            folder = turned_folder(rotation, todo)
            if folder:
                run(readers[0], folder, rotation)
        by_rotation: dict = {}
        for n in unread():
            if lying[n]:
                way_up = max(sorted(lying[n]), key=lambda r: (lying[n][r], r == 0))
                if way_up:
                    by_rotation.setdefault(way_up, []).append(n)
        for rotation, numbers in sorted(by_rotation.items()):
            for reader in readers[1:]:
                todo = [n for n in numbers if n in set(unread())]
                if not todo:
                    break
                folder = turned_folder(rotation, todo)
                if folder:
                    run(reader, folder, rotation)

    return {"best": best, "ink": ink, "problems": problems, "count": count}


def merge(parts: list[dict]) -> Outcome:
    """The pieces of one scan, in page order, as one outcome."""
    for part in parts:
        if part.get("fatal"):
            return Outcome(False, error=part["fatal"])
    count = parts[0]["count"] if parts else 0
    best, ink, problems = {}, {}, []
    for part in parts:
        best.update(part["best"])
        ink.update(part["ink"])
        problems += part["problems"]
    if not ink:
        return Outcome(False, error="no pages", page_count=count)
    texts = [best[n].text for n in sorted(best)]
    outcome = Outcome(True, "\n\n".join(texts) + "\n", pages=len(best), page_count=count, problems=problems[:10])
    if sorted(best) == list(range(1, len(best) + 1)):      # every page from the first: where each one starts
        from contextmax.docs.readers import page_starts

        outcome.page_lines = page_starts(texts, 2)
    for n, p in best.items():
        if p.text.strip():
            outcome.readers[p.reader] = outcome.readers.get(p.reader, 0) + 1
            outcome.turned += bool(p.rotation)
            outcome.doubtful += _not_read(p, ink[n])            # kept, as the best there was, but said
        else:
            outcome.empty += 1
    if not outcome.readers:
        return Outcome(False, error="; ".join(problems[:3]) or "text recognition found no text", pages=len(best),
                       page_count=count)
    return outcome
