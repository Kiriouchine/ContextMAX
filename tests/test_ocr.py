"""Text recognition: what reads as words, the page layout, the choice of reader, language and turn per
page, the build's handling of scans, and the real RapidOCR on a made-up scan. Windows' recognition
itself is exercised outside the test suite (it needs PowerShell and an installed language)."""
from __future__ import annotations

import hashlib
import math
import zipfile
from pathlib import Path

import pytest

from contextmax.docs import ocr
from contextmax.docs.ocr import Line


def test_words_read_as_words_and_a_wrong_script_does_not():
    good, _ = ocr.wordlike_share("The pump P-101 delivers 4,5 m3/h at 23 °C ± 2 °C; mA, kWh and MHz are units.")
    russian, _ = ocr.wordlike_share("Раздел 5. Требования к источнику питания")
    lookalike, _ = ocr.wordlike_share("Pa3Aen 5. Tpe60BaHMA K MCTOHHMKY nv•1TaHVIA")       # Russian read as Latin
    turned, _ = ocr.wordlike_share("o\nd\nc o\n0 Q)\no c")                                  # a page on its side
    assert good > 0.95 and russian > 0.95
    assert lookalike < 0.5 and turned < 0.3
    assert ocr.wordlike_share("") == (0.0, 0)


@pytest.mark.parametrize("text", ["当绕组温度超过一百三十五度时，应报告过热故障。", "温度が百三十五度を超えたら、過熱を報告する。",
                                  "온도가 백삼십오 도를 넘으면 과열을 알린다", "يجب أن يبلغ عن ارتفاع درجة الحرارة",
                                  "יש לדווח על חום יתר", "電 機 控 制 要 求"])
def test_scripts_without_capitals_read_as_words(text):
    assert ocr.wordlike_share(text)[0] > 0.9


def test_a_table_reads_row_by_row():
    lines = [Line(170, 260, 125, 22, "Parameter"), Line(690, 258, 70, 21, "Value"), Line(970, 255, 50, 21, "Unit"),
             Line(170, 300, 240, 29, "max_phase_current"), Line(690, 298, 50, 22, "12.5"), Line(970, 300, 12, 22, "A"),
             Line(170, 340, 210, 28, "fault_temperature"), Line(690, 339, 45, 22, "135"), Line(970, 336, 64, 27, "degC")]
    expected = "Parameter\tValue\tUnit\nmax_phase_current\t12.5\tA\nfault_temperature\t135\tdegC"
    assert ocr.layout(lines, 1650) == expected
    # the same table on a scan slanted 2.5 degrees: each cell lower the further right it is
    slope = math.tan(math.radians(2.5))
    slanted = [Line(ln.left, ln.top + (ln.left + ln.width / 2) * slope, ln.width, ln.height, ln.text) for ln in lines]
    assert ocr.layout(slanted, 1650) != expected
    assert ocr.layout(slanted, 1650, 2.5) == expected


def test_two_columns_read_column_by_column_with_a_title_across():
    title = Line(170, 100, 1300, 30, "Section 7 Installation notes across both columns")
    left = [Line(170, 200 + 40 * i, 560, 28, f"left line {i}") for i in range(5)]
    right = [Line(880, 200 + 40 * i, 560, 28, f"right line {i}") for i in range(5)]
    text = ocr.layout(right + [title] + left, 1650).splitlines()
    assert text == [title.text] + [ln.text for ln in left] + [ln.text for ln in right]


class FakeReaders:
    """Pages and what each reader makes of them: {page: {reader: text}}; a reader is "windows en-GB",
    "windows ru", "rapidocr default", "rapidocr cyrillic", or any of them with "@90" for a turned page.
    A text given as ("text", "standing") comes in boxes standing on end, as RapidOCR sees a turned page."""

    def __init__(self, monkeypatch, pages: dict, ink: dict | None = None, windows=("en-GB", "nl-NL", "ru"),
                 rapid=("default", "cyrillic")):
        self.pages, self.calls = pages, []
        ink = ink or {n: 0.05 for n in pages}

        def render(pdf_path, out_dir, pages_wanted=None, rotation=0):
            out_dir.mkdir(parents=True, exist_ok=True)
            for n in pages if pages_wanted is None else [i + 1 for i in pages_wanted]:
                (out_dir / f"page-{n:04d}.png").write_bytes(b"")
            return ({n: ink[n] for n in pages}, len(pages))

        def numbers(folder):
            return sorted(int(p.stem[5:]) for p in folder.glob("page-*.png"))

        def turn(folder):
            return "@" + folder.name.split("-")[1] if folder.name.startswith("turned-") else ""

        def read_windows(folder, language, timeout):
            used = language or windows[0]
            self.calls.append(f"windows {used}{turn(folder)} {numbers(folder)}")
            return ({n: self._lines(n, f"windows {used}{turn(folder)}") for n in numbers(folder)}, used, "")

        def read_rapid(folder, model):
            self.calls.append(f"rapidocr {model}{turn(folder)} {numbers(folder)}")
            return {n: self._lines(n, f"rapidocr {model}{turn(folder)}") for n in numbers(folder)}

        monkeypatch.setattr(ocr, "render", render)
        monkeypatch.setattr(ocr, "_read_windows", read_windows)
        monkeypatch.setattr(ocr, "_read_rapid", read_rapid)
        monkeypatch.setattr(ocr, "rapid_models", lambda: list(rapid))
        self.windows = list(windows)

    def _lines(self, n, reader):
        text, shape = self.pages[n].get(reader, ""), "lying"
        if isinstance(text, tuple):
            text, shape = text
        boxes = []
        for i, t in enumerate(text.splitlines()):
            w, h = 20 * len(t), 30
            boxes.append(Line(100, 100 + 40 * i, w, h, t) if shape == "lying" else Line(100 + 40 * i, 100, h, w, t))
        return (boxes, 1650.0, 0.0, "")


ENGLISH = "The motor controller shall limit the phase current to 12.5 A during start-up"
RUSSIAN = "Напряжение питания должно находиться в диапазоне от 18 до 32 вольт"
LOOKALIKE = "Hanpgxewqe nv•1TaHVIA AOJIXHO HaXOAhTbCA B AnanaaoHe"


def test_each_page_gets_the_language_that_reads_it(monkeypatch):
    fake = FakeReaders(monkeypatch, {1: {"windows en-GB": ENGLISH}, 2: {"windows en-GB": LOOKALIKE, "windows ru": RUSSIAN}})
    out = ocr.read_pdf("x.pdf", fake.windows)
    assert out.ok and out.text == f"{ENGLISH}\n\n{RUSSIAN}\n"
    assert out.readers == {"windows en-GB": 1, "windows ru": 1}
    # the English page is read once; only the unread page goes to the other languages
    assert fake.calls == ["windows en-GB [1, 2]", "windows nl-NL [2]", "windows ru [2]"]


def test_a_page_on_its_side_is_turned_and_half_sense_from_standing_lines_does_not_count(monkeypatch):
    fake = FakeReaders(monkeypatch, {1: {"windows en-GB": "o\nd\nc o", "windows en-GB@90": ENGLISH,
                                         "rapidocr default": ("half sense of the turned page", "standing")}})
    out = ocr.read_pdf("x.pdf", fake.windows)
    assert out.text == ENGLISH + "\n" and out.turned == 1 and out.readers == {"windows en-GB": 1}


def test_a_page_on_its_side_in_another_script_is_read_that_way_up_by_every_reader(monkeypatch):
    fake = FakeReaders(monkeypatch, {1: {"windows en-GB": "o\nd", "windows en-GB@90": LOOKALIKE, "windows ru@90": RUSSIAN}})
    out = ocr.read_pdf("x.pdf", fake.windows)
    assert out.text == RUSSIAN + "\n" and out.turned == 1 and out.readers == {"windows ru": 1}
    assert "windows ru@90 [1]" in fake.calls and "windows ru@270 [1]" not in fake.calls


def test_without_windows_recognition_rapidocr_reads_and_cyrillic_follows(monkeypatch):
    fake = FakeReaders(monkeypatch, {1: {"rapidocr default": ENGLISH},
                                     2: {"rapidocr default": "5 .", "rapidocr cyrillic": RUSSIAN}}, windows=())
    out = ocr.read_pdf("x.pdf", [])
    assert out.text == f"{ENGLISH}\n\n{RUSSIAN}\n"
    assert fake.calls == ["rapidocr default [1, 2]", "rapidocr cyrillic [2]"]


def test_a_page_of_chinese_beats_a_few_junk_words(monkeypatch):
    chinese = "第三章 电机控制要求\n电机控制器应在启动期间将相电流限制为十二安培。\n当绕组温度超过一百三十五度时，应报告过热故障。"
    fake = FakeReaders(monkeypatch, {1: {"windows en-GB": "Ilk\nIll\n11", "windows en-GB@90": "Ill\n-k",
                                         "rapidocr default": chinese}})
    out = ocr.read_pdf("x.pdf", fake.windows)
    assert out.text == chinese + "\n" and out.readers == {"rapidocr default": 1}


def test_a_blank_page_is_not_tried_again_but_a_short_page_in_another_script_is(monkeypatch):
    fake = FakeReaders(monkeypatch, {1: {"windows en-GB": ENGLISH}, 2: {},
                                     3: {"windows en-GB": "Pa3Aen 5.", "windows ru": "Раздел 5."}},
                       ink={1: 0.05, 2: 0.0005, 3: 0.0009}, rapid=())
    out = ocr.read_pdf("x.pdf", fake.windows)
    assert out.ok and out.empty == 1 and out.text.endswith("Раздел 5.\n")
    assert fake.calls[:3] == ["windows en-GB [1, 2, 3]", "windows nl-NL [3]", "windows ru [3]"]


def test_no_reader_at_all_is_said(monkeypatch):
    monkeypatch.setattr(ocr, "rapid_models", lambda: [])
    out = ocr.read_pdf("x.pdf", [])
    assert not out.ok and "no text recognition" in out.error


def test_a_rapidocr_that_cannot_start_is_each_page_s_reason_not_a_crash(tmp_path, monkeypatch):
    (tmp_path / "page-0001.png").write_bytes(b"")
    (tmp_path / "page-0002.png").write_bytes(b"")

    def broken(model):
        raise RuntimeError("Load model failed")

    monkeypatch.setattr(ocr, "_rapid_engine", broken)
    out = ocr._read_rapid(tmp_path, "cyrillic")
    assert sorted(out) == [1, 2] and all("Load model failed" in error for _, _, _, error in out.values())


def test_a_model_that_does_not_match_its_sha256_is_not_kept_nor_used(tmp_path, monkeypatch):
    source, target = tmp_path / "from", tmp_path / "to"
    source.mkdir()
    (source / "m.onnx").write_bytes(b"model bytes")
    good = hashlib.sha256(b"model bytes").hexdigest()
    monkeypatch.setattr(ocr, "RAPID_MODELS", {"x": ("m.onnx", hashlib.sha256(b"other bytes").hexdigest())})
    with pytest.raises(OSError, match="does not match"):
        ocr.fetch_models(target, source)
    assert not any(target.iterdir())
    monkeypatch.setattr(ocr, "RAPID_MODELS", {"x": ("m.onnx", good)})
    assert ocr.fetch_models(target, source) == ["x model: copied (0 MB)"]
    assert ocr.fetch_models(target, source) == ["x model: already there"]
    # a file changed on disk is not used, and the next fetch replaces it
    (target / "m.onnx").write_bytes(b"damaged")
    monkeypatch.setattr(ocr, "_MODEL_OK", {})
    monkeypatch.setattr(ocr, "rapid_problem", lambda: "")
    monkeypatch.setenv("CONTEXTMAX_OCR_MODELS", str(target))
    assert ocr.rapid_models() == ["default"]
    assert ocr.fetch_models(target, source) == ["x model: copied (0 MB)"]


def test_a_scan_that_could_not_be_read_is_not_read_again_until_something_changes(tmp_path, monkeypatch):
    from contextmax.docs import textcache

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF")
    calls = []

    def read_pdf(src, languages):
        calls.append(src)
        if len(calls) == 1:
            raise RuntimeError("a reader broke")
        return ocr.Outcome(False, error="text recognition found no text")

    monkeypatch.setattr(ocr, "read_pdf", read_pdf)
    monkeypatch.setattr(ocr, "rapid_models", lambda: ["default"])
    row = {"needs_ocr": True, "ext": ".pdf", "method": "pdfium", "folder": "f", "relative_path": "scan.pdf",
           "key": "scan"}
    roots = {"f": str(tmp_path)}
    assert textcache._ocr_pass([row], roots, tmp_path, ["en-GB"]) == 0        # the crash is the scan's reason
    assert "a reader broke" in row["ocr_problem"] and row["ocr_tried"]
    textcache._ocr_pass([row], roots, tmp_path, ["en-GB"])
    assert len(calls) == 1                                                     # the same readers: not again
    textcache._ocr_pass([row], roots, tmp_path, ["en-GB", "ru"])
    textcache._ocr_pass([row], roots, tmp_path, ["en-GB", "ru"], retry=True)
    assert len(calls) == 3                                                     # a new reader, then --full


def test_rapidocr_reads_a_made_up_scan(tmp_path):
    if ocr.rapid_problem():
        pytest.skip(ocr.rapid_problem())
    pdfium = pytest.importorskip("pypdfium2")
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("arial.ttf", 46)
    except OSError:
        pytest.skip("no Arial font")
    img = Image.new("L", (1654, 2339), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(["Drive control requirements", "The supply voltage range is 18 V to 32 V."]):
        draw.text((180, 200 + 80 * i), line, font=font, fill=0)
    jpeg = tmp_path / "page.jpg"
    img.convert("RGB").save(jpeg, quality=85)
    pdf = pdfium.PdfDocument.new()
    image = pdfium.PdfImage.new(pdf)
    with open(jpeg, "rb") as fh:
        image.load_jpeg(fh, inline=True)
    image.set_matrix(pdfium.PdfMatrix().scale(595, 842))
    page = pdf.new_page(595, 842)
    page.insert_obj(image)
    page.gen_content()
    pdf.save(str(tmp_path / "scan.pdf"))
    pdf.close()
    out = ocr.read_pdf(str(tmp_path / "scan.pdf"), [])
    assert out.ok and out.readers == {"rapidocr default": 1}
    assert "Drive control requirements" in out.text and "18 V to 32 V" in out.text


def test_the_offline_lock_pins_every_wheel_by_sha256(tmp_path):
    from contextmax import bundle

    wheel = tmp_path / "et_xmlfile-2.0.0-py3-none-any.whl"
    wheel.write_bytes(b"zip")
    assert bundle.lock_lines([wheel]) == [f"et_xmlfile==2.0.0 --hash=sha256:{hashlib.sha256(b'zip').hexdigest()}"]
    with pytest.raises(bundle.BundleError):
        bundle.lock_lines([tmp_path / "pkg-1.0.tar.gz"])


def test_the_offline_installer_lists_licences_and_the_lgpl_sources(tmp_path):
    from contextmax import bundle

    wheel = tmp_path / "shapely-2.2.0-cp314-cp314-win_amd64.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("shapely-2.2.0.dist-info/METADATA", "Metadata-Version: 2.4\nName: shapely\nVersion: 2.2.0\n"
                                                       "License-Expression: BSD-3-Clause\n\nlong description")
    text = bundle.third_party([wheel])
    assert "shapely 2.2.0: BSD-3-Clause" in text and "GEOS (LGPL-2.1)" in text


def test_the_offline_installer_carries_the_program_only_and_never_into_its_own_folder(tmp_path):
    from contextmax import bundle

    source = Path(__file__).resolve().parents[1]
    with pytest.raises(bundle.BundleError, match="folder itself"):
        bundle.make(source, source)
    bundle._copy_program(source, tmp_path / "copy")
    names = sorted(p.name for p in (tmp_path / "copy").iterdir())
    assert names == sorted(n for n in bundle.PROGRAM if (source / n).exists())
    assert not list((tmp_path / "copy").rglob("__pycache__"))


def test_the_offline_installer_uses_the_python_setup_cmd_names():
    from contextmax import bundle

    values = bundle.setup_values(Path(__file__).resolve().parents[1])
    assert values["PYVER"].count(".") == 2 and len(values["PYSHA256"]) == 64
