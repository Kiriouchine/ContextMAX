"""Values with their exact place, names from their sentence, values in the code, and one way to cite."""
import json
import shutil

import pytest

from contextmax import ask, citations, util
from contextmax.code import values as V
from contextmax.docs import corpus, readers, value_code
from contextmax.docs import params as P

# == where a value is ==


def _pdf(pages: list[list[str]]) -> bytes:
    """A PDF with a text layer, one list of lines per page."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    n = len(pages)
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{3 + 2 * i} 0 R" for i in range(n)) + f"] /Count {n} >>"]
    for i, lines in enumerate(pages):
        content = "BT /F1 11 Tf 72 760 Td 14 TL " + " ".join(f"({esc(t)}) Tj T*" for t in lines) + " ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {3 + 2 * n} 0 R >> >> >>")
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def test_a_pdf_records_where_each_page_starts_and_a_value_knows_its_page(tmp_path):
    pytest.importorskip("pypdfium2")
    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(_pdf([["1 Introduction", "Nothing to measure here."],
                          ["2 Control loop", "The loop uses a settle time of 12 ms.", "Output limit: 1000 counts"]]))
    meta = readers.read_pdf(str(pdf), str(tmp_path / "spec.txt"))
    text = (tmp_path / "spec.txt").read_text(encoding="utf-8")
    lines = text.split("\n")
    assert meta["pages"] == 2 and meta["page_lines"][0] == 1
    assert lines[meta["page_lines"][1] - 1].startswith("2 Control loop")
    _, rows = corpus._doc_parameters(text, corpus.Rules({}), ".pdf", meta["page_lines"])
    settle = next(r for r in rows if r["value_as_written"] == "12")
    assert settle["page"] == 2 and "settle time of 12 ms" in lines[settle["line_no"] - 1]
    assert settle["label"] == "settle time" and settle["label_source"] == "sentence"
    assert settle["section"] == "2 Control loop" and settle["sentence"].endswith("settle time of 12 ms.")
    limit = next(r for r in rows if r["value_as_written"] == "1000")
    assert limit["label_source"] == "label" and limit["page"] == 2
    assert citations.value(dict(settle, stage="Design"), "Spec") == f"Spec · Design · page 2, line {settle['line_no']} · §2 Control loop"


def test_page_starts_count_the_lines_each_page_takes():
    assert readers.page_starts(["a\nb", "c", "d\ne\nf"], 1) == [1, 3, 4]
    assert readers.page_starts(["a\nb", "c"], 2) == [1, 4]          # recognised scans: a blank line between pages


def test_a_recognised_scan_says_where_each_page_starts():
    from contextmax.docs import ocr

    page = ocr.PageText()
    parts = [{"best": {1: ocr.PageText("one\ntwo", "rapidocr default"), 2: ocr.PageText("three", "rapidocr default")},
              "ink": {1: 0.1, 2: 0.1}, "problems": [], "count": 2}]
    out = ocr.merge(parts)
    assert out.ok and out.page_lines == [1, 4] and out.text.split("\n")[3] == "three"
    assert page.text == ""


def test_the_gate_checks_that_each_line_shows_its_value():
    lines = ["# 2 Loop", "a settle time of 12 ms", "varied from 35 to", "150 mm, in steps"]
    row = {"origin": "prose_value", "value_as_written": "12", "line_no": 2, "page": None, "label": "settle time",
           "label_source": "sentence"}
    assert corpus._place_problem(row, lines, None) is None
    assert "does not show" in corpus._place_problem(dict(row, line_no=1), lines, None)
    assert "past the end" in corpus._place_problem(dict(row, line_no=9), lines, None)
    assert corpus._place_problem(dict(row, value_as_written="35~150", line_no=3), lines, None) is None   # across lines
    assert "not on page" in corpus._place_problem(dict(row, page=3), lines, [1, 3])
    assert "where it comes from" in corpus._place_problem(dict(row, label_source=None), lines, None)


# == names from their sentence ==

@pytest.mark.parametrize("before, name", [
    ("a settle time of ", "settle time"),
    ("The supply voltage shall be ", "supply voltage"),
    ("the controller shall keep the gain margin at ", "gain margin"),
    ("with a sample time Ts of ", "sample time"),
    ("The maximum motor current shall not exceed ", "maximum motor current"),
    ("In Figure 3 the cutoff frequency (fc) is approximately ", "cutoff frequency"),
    ("beacons every 7 m, with an update rate of ", "update rate"),
    ("The gain is ", None),                                          # one word: everywhere
    ("the total time of ", None),                                    # only generic words
    ("The motor shall operate at ", None),
    ("The rotational speed of the drive shaft is ", None),          # names the speed, not the shaft
    ("a sti\x1eness of ", None),                                     # a lost ligature splits no name
    ("The two booms are ", None),
    ("In this case tc is equal to ", None),
    ("from sine wave is ", None),                                    # the name began on the line before
    ("It also has custom drive electronics consisting of ", None),
    ("by a much higher value of ", None),                            # a comparison: the user's mark, s21
    ("with a higher accuracy of ", None),                            # s40
    ("one measurement cycle takes ", None),
    ("so the external resis\ufffetance required is ", "external resistance required"),   # s48: a word a PDF broke
    ("As the average sensor-actuator distance is of ", "average sensor-actuator distance"),
    ("RTK GPS has centimetre accuracies of ", "centimetre accuracies"),       # the name starts after the verb
    ("a motor with rated current of ", "rated current"),
    ("the speed of drive shaft is ", None),                          # never after "of"
    ("For instance, for a manipulator with a maximum reach of ", "maximum reach"),   # "reach" is a noun here
])
def test_a_value_is_named_by_the_words_before_it_or_not_at_all(before, name):
    assert corpus.sentence_name(before) == name


@pytest.mark.parametrize("before, name, symbol", [
    ("and for a total energy E = ", "total energy", "E"),            # the user's marks, s05 and s07
    ("Added step disturbance w = ", "Added step disturbance", "w"),
    ("In Figure 3 the cutoff frequency (fc) is approximately ", "cutoff frequency", "fc"),
    ("Real time kinetic (RTK) GPS setups have a centimetre accuracies of ", "centimetre accuracies", None),
])
def test_the_symbol_written_with_a_name_is_kept_beside_it(before, name, symbol):
    assert corpus.name_and_symbol(before) == (name, symbol)


def test_values_in_one_list_share_their_name_and_a_word_broken_over_lines_is_joined():
    text = ("tested at a transmission distance of 21.21 mm (224 kHz), 30.21 mm (100 kHz) and later 5 s.\n"
            "The natural frequencies are 128.3 rad/s and 104.8 rad/s instead of 117.1 rad/s.\n"
            "so the needed resis-\ntance required is 20.5 ohm.")
    named = {(p["value"], p["prose_label"]) for p in corpus.outline_of(text, corpus.Rules({}), ".txt")["_all"]}
    assert named == {("21.21", "transmission distance"), ("224", None), ("30.21", "transmission distance"), ("100", None),
                     ("5", None), ("128.3", "natural frequencies"), ("104.8", "natural frequencies"), ("117.1", None),
                     ("20.5", "resistance required")}


def test_a_range_is_written_with_a_tilde_whichever_way_the_document_writes_it():
    text = "accuracies of 1 cm - 4 cm here. Also 1~4 cm, from 35 mm to 150 mm, 0.5-1 s, and 5 V - 3 A."
    found = [(p["value"], p["unit"], p["kind"]) for p in corpus.outline_of(text, corpus.Rules({}), ".txt")["_all"]]
    assert found == [("1~4", "cm", "range"), ("1~4", "cm", "range"), ("35~150", "mm", "range"), ("0.5~1", "s", "range"),
                     ("5", "V", "value"), ("3", "A", "value")]
    assert P.canon_number("4–20") == P.canon_number("4~20.0") == "4~20"      # as earlier versions wrote it
    assert P.all_numbers("1~4") and not P.all_numbers("1-4")


def test_numbers_of_figures_and_of_references_are_not_values():
    text = ("Fig. 76.16 A mobile robot with a camera\n192 A. Smith and C.A. Jones\n236 K.A. Brown\n"
            "30 A-star Algorithm\nThe supply is 5 V. The motor draws 2 A.\n12 V supply\n"
            "a square cross section 10 mm wide, a device with no 0 g offset, see Table 9.2 A table")
    found = [(p["value"], p["unit"]) for p in corpus.outline_of(text, corpus.Rules({}), ".txt")["_all"]]
    assert found == [("5", "V"), ("2", "A"), ("12", "V"), ("10", "mm"), ("0", "g")]


def test_a_unit_is_on_its_number_s_line_and_written_with_its_capitals():
    text = ("Lane, 37\nK. Smith\n0.0\ng -0-5\na12 - 2771340 -3233230\na13 - 924\nVIDEO 203 A robotic team\n37 K and 5 V\n"
            "G(s)= 1\ns +1\nabout 0.850 kg of mass and 1.2\nm of wingspan, a pulse of 5\nµs. The sensor\n"
            "the error is about 2 to 3\ncm.")
    found = [(p["value"], p["unit"]) for p in corpus.outline_of(text, corpus.Rules({}), ".txt")["_all"]]
    assert found == [("37", "K"), ("5", "V"), ("0.850", "kg"), ("1.2", "m"), ("5", "µs"), ("2~3", "cm")]


def test_a_list_of_values_under_one_name_gives_the_same_conflict_row_whatever_the_set_order():
    import subprocess
    import sys

    code = ("from contextmax.docs import corpus as C\n"
            "rows = [dict(label='natural frequencies', label_norm='natural frequencies', origin='prose_value', value_norm=v,"
            " unit_norm='rad/s', unit='rad/s', value_shown=v, doc_ref=d, sheet=None, cell=None, line_no=1)"
            " for d in ('A', 'B') for v in ('128.3', '104.8', '117.1', '99.5')]\n"
            "print(C.value_conflicts(C.value_owners(rows))[0]['value'])\n")
    seen = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={**__import__("os").environ, "PYTHONHASHSEED": str(seed)}).stdout for seed in range(6)}
    assert seen == {"104.8 rad/s\n"}


def test_a_decade_is_not_a_duration_and_pdf_marks_are_not_shown():
    parsed = corpus.outline_of("Robots spread in the early 1980s.\nA settle time of 12 ms.", corpus.Rules({}), ".txt")
    assert [p["value"] for p in parsed["_all"]] == ["12"]
    assert corpus._readable("eigen￾frequencies 12 ms", 22, 24) == "eigenfrequencies 12 ms"


# == values in the code ==

C_SOURCE = """#define PID_SETTLE_TIME_MS   12      /* settle time */
#define CHANNEL_A            3
#define MOTOR_MAX_CURRENT_A  (2.5f)  // peak current
#define PWM_FREQ             20000U  /**< PWM frequency [Hz] */
#define LOOP_MASK            0x1F
// #define OLD_GAIN 5
static const float SAMPLE_TIME_S = 0.001f; // sample time in ms
int not_const = 4;
constexpr double kRiseTimeUs{350.0};
"""


def test_named_numbers_in_c_with_their_units():
    rows = {r["name"]: r for r in V._c_values(C_SOURCE, "C")}
    assert set(rows) == {"PID_SETTLE_TIME_MS", "CHANNEL_A", "MOTOR_MAX_CURRENT_A", "PWM_FREQ", "SAMPLE_TIME_S", "kRiseTimeUs"}
    assert (rows["PID_SETTLE_TIME_MS"]["unit"], rows["PID_SETTLE_TIME_MS"]["unit_from"]) == ("ms", "name")
    assert rows["CHANNEL_A"]["unit"] == ""                           # a channel, not amperes
    assert rows["MOTOR_MAX_CURRENT_A"]["unit"] == "A" and rows["MOTOR_MAX_CURRENT_A"]["value"] == "2.5"
    assert (rows["PWM_FREQ"]["unit"], rows["PWM_FREQ"]["unit_from"]) == ("Hz", "comment")
    assert rows["SAMPLE_TIME_S"]["unit"] == "" and "name says s, the comment says ms" in rows["SAMPLE_TIME_S"]["unit_note"]
    assert rows["kRiseTimeUs"]["unit"] == "us" and rows["PID_SETTLE_TIME_MS"]["line"] == 1


def test_named_numbers_in_python_matlab_and_vhdl():
    py = {r["name"]: r for r in V._python_values('TIMEOUT_MS = 250  # request timeout\nclass Config:\n'
                                                   '    SETTLE_TIME: float = 0.012  # [s]\n    NAME = "pid"\n')}
    assert py["TIMEOUT_MS"]["unit"] == "ms" and py["Config.SETTLE_TIME"]["unit"] == "s" and "Config.NAME" not in py
    m = {r["name"]: r for r in V._matlab_values("Ts = 1e-3;  % sample time [s]\n% x = 4;\nfor i = 1:10\n"
                                                 "settle_time_ms = 12; gain = 3;\n")}
    assert m["Ts"]["unit"] == "s" and m["Ts"]["comment"] == "sample time [s]" and m["settle_time_ms"]["unit"] == "ms"
    assert "x" not in m and "i" not in m
    vh = {r["name"]: r for r in V._vhdl_values("entity e is\n  generic (\n    CLK_FREQ_HZ : integer := 50_000_000;\n"
                                                "    DEAD_TIME : time := 200 ns\n  );\nend entity;\narchitecture a of e is\n"
                                                "  constant SETTLE_CYCLES : natural := 1200; -- settle time in cycles\n"
                                                "  -- constant OLD : integer := 4;\nbegin end architecture;\n")}
    assert vh["CLK_FREQ_HZ"]["value"] == "50000000" and vh["CLK_FREQ_HZ"]["unit"] == "Hz"
    assert (vh["DEAD_TIME"]["unit"], vh["DEAD_TIME"]["unit_from"]) == ("ns", "literal") and "OLD" not in vh
    assert vh["SETTLE_CYCLES"]["line"] == 8


@pytest.mark.parametrize("doc, unit, bound, code, code_unit, outcome, says", [
    ("12", "ms", "", "0.012", "s", "match", "= 12 ms"),
    ("12", "ms", "", "15", "ms", "mismatch", "15 ms in the code"),
    ("5~10", "V", "", "7.5", "V", "match", ""),
    ("6", "dB", "min", "9", "dB", "match", "at least"),
    ("2", "A", "max", "2.5", "A", "mismatch", "at most"),
    ("12", "ms", "", "0.012", "", "unit unknown", "would match if it were in s"),
    ("1000", "counts", "", "1000", "", "unit unknown", "the numbers are the same"),
    ("12", "ms", "", "12", "V", "units differ", ""),
    ("90", "deg", "", "1.5708", "rad", "match", ""),
    ("90", "deg", "", "1.6", "rad", "match", ""),            # pi/2 written to one decimal
    ("90", "deg", "", "1.7", "rad", "mismatch", ""),
])
def test_a_document_value_against_a_code_value_in_one_unit(doc, unit, bound, code, code_unit, outcome, says):
    got, note = value_code.compare(doc, unit, bound, code, code_unit)
    assert got == outcome and says in note


def _vrow(label, value, unit, doc="D1", line=3, sentence=""):
    return {"label": label, "label_norm": P.canon_label(label), "origin": "prose_value", "kind": "value",
            "value_norm": P.canon_number(value), "value_shown": value, "value_as_written": value, "unit": unit,
            "unit_norm": P.canon_unit(unit), "doc_ref": doc, "file_key": doc, "line_no": line, "sentence": sentence,
            "context": sentence or f"{label} {value} {unit}"}


def _crow(name, value, unit="", comment="", line=1):
    r = V._row("C", "define", name, value, line, comment)
    return dict(r, unit=unit or r["unit"], file="pid.h", target="fw", target_label="firmware", module="control")


def test_document_names_meet_code_names_and_ambiguity_is_said():
    docs = [_vrow("settle time", "12", "ms"), _vrow("settle time", "15", "ms", doc="D2"), _vrow("gain", "3", "")]
    code = [_crow("PID_SETTLE_TIME_MS", "12"), _crow("SPEED_SETTLE_TIME_MS", "20", line=2), _crow("GAIN", "3")]
    rows = value_code.links(docs, code)
    assert {(r["code"]["name"], r["doc_value"], r["outcome"]) for r in rows} == {
        ("PID_SETTLE_TIME_MS", "12", "match"), ("PID_SETTLE_TIME_MS", "15", "mismatch"),
        ("SPEED_SETTLE_TIME_MS", "12", "mismatch"), ("SPEED_SETTLE_TIME_MS", "15", "mismatch")}
    assert all(r["candidates_count"] == 2 for r in rows)              # two code names could be it: both are listed
    by_comment = value_code.links([_vrow("settle time", "12", "ms")], [_crow("T_SET", "12", "ms", "settle time [ms]")])
    assert [(r["matched_by"], r["outcome"]) for r in by_comment] == [("the code's comment", "match")]
    assert value_code.links([_vrow("sampling frequency", "400", "Hz")],
                            [_crow("FREQ_RED", "1", comment="sampling frequency reducing parameter")]) == []


def test_a_value_without_a_name_meets_the_code_by_its_number_and_its_words():
    plain = dict(_vrow("", "2000", "Hz", sentence="The sensor shall be sampled at 2000 Hz."), label=None, label_norm="")
    rows = value_code.links([plain], [_crow("SENSOR_SAMPLE_HZ", "2000"), _crow("PWM_FREQ_HZ", "2000", line=2)])
    assert [(r["code"]["name"], r["outcome"]) for r in rows] == [("SENSOR_SAMPLE_HZ", "match")]
    assert rows[0]["matched_by"].startswith("the same number") and rows[0]["doc_sentence"].startswith("The sensor")
    assert value_code.links([dict(plain, sentence="The pump runs at 2000 Hz.")], [_crow("SENSOR_SAMPLE_HZ", "2000")]) == []


def test_the_demo_compares_its_values_with_its_code_and_the_gate_holds_it(built, tmp_path):
    rows = util.load_jsonl(built.documents_dir / "links" / "value-to-code.jsonl")
    seen = {(r["label"], r["doc_shown"], r["code"]["name"], r["outcome"]) for r in rows}
    assert ("settle time", "12 ms", "PID_SETTLE_TIME_MS", "match") in seen
    assert ("settle time", "15 ms", "PID_SETTLE_TIME_MS", "mismatch") in seen
    assert ("", "2000 Hz", "SENSOR_SAMPLE_HZ", "match") in seen
    code = util.load_jsonl(built.code_dir / "firmware" / "values.jsonl")
    assert any(r["name"] == "PID_SETTLE_TIME_MS" and r["file"] == "control/inc/pid.h" for r in code)
    errors, _ = corpus.validate(built)
    assert errors == []
    path = built.documents_dir / "links" / "value-to-code.jsonl"
    keep = path.read_bytes()
    try:
        changed = [dict(r, outcome="match") for r in rows]
        path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in changed) + "\n", encoding="utf-8")
        errors, _ = corpus.validate(built)
        assert any("value-to-code" in e for e in errors)
    finally:
        path.write_bytes(keep)


def test_every_value_of_the_demo_cites_its_line(built):
    rows = util.load_jsonl(built.documents_dir / "params.jsonl")
    prose = [r for r in rows if r["origin"] == "prose_value"]
    assert prose and all(r["line_no"] for r in prose)
    pdf = [r for r in prose if r["ext"] == ".pdf"]
    assert pdf and all(r["page"] == 1 for r in pdf)
    assert {r["label_source"] for r in rows if r.get("label")} >= {"label", "cell"}
    import sqlite3

    con = sqlite3.connect(built.documents_dir / "params.sqlite")
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == P.FORMAT_VERSION == 2
        assert con.execute("SELECT count(*) FROM places WHERE line_no IS NOT NULL").fetchone()[0] > 0
    finally:
        con.close()


# == the local model looks things up ==

def test_a_window_is_the_passage_around_the_cited_line_and_every_quote_is_checked(built):
    from contextmax import reading

    entry = next(e for e in reading.ways_in(built, "settle time") if e.get("key") == "Detailed_design_v2.1")
    w = reading.open_window(built, entry)
    shown = reading.numbered(w)
    assert f"{entry['line']}: " in shown and "settle time" in shown.lower()
    assert w["cite"].startswith("Detailed design") and "line" in w["cite"]
    line = next(w["first"] + i for i, text in enumerate(w["lines"]) if "settle time" in text.lower())
    text = w["lines"][line - w["first"]]
    got = reading.check(w, {"quotes": [
        {"line": line, "text": text},                                 # at its line
        {"line": w["first"], "text": text},                           # in the window, at another line: set right
        {"line": line, "text": "the settle time is 99 hours"},        # not in the file
    ]})
    assert [q["line"] for q in got["held"]] == [line, line] and len(got["missing"]) == 1
    code = next(e for e in reading.ways_in(built, "How does read_sensor remove the offset?") if e["kind"] == "code")
    cw = reading.open_window(built, code)
    assert "read_sensor" in reading.numbered(cw) and cw["cite"].startswith("firmware · ")
    # what a passage points to is found: a function by its name, a document by its title
    nxt = reading.follow(built, w, ["read_sensor", "Test plan", "This passage points to the test result for the answer"], set())
    assert {n["kind"] for n in nxt} == {"code", "document"} and len(nxt) == 2       # a sentence is no pointer
    assert reading.follow(built, w, ["Test plan"], {reading._place(n) for n in nxt}) == []   # read already
    assert reading.parse("noise {\"relevant\": true, \"quotes\": [], \"says\": \"x\", \"follow\": []}")["relevant"]
    assert reading.parse("no json")["unparsed"]


def test_a_pdf_page_is_drawn_for_a_model_that_can_see(built):
    from pathlib import Path

    from contextmax.docs import ocr

    pdf = next(p for f in built.folders for p in sorted(Path(f.path).rglob("*.pdf")))
    png = ocr.page_png(str(pdf), 0)
    assert png.startswith(b"\x89PNG") and len(png) > 1000


def test_nothing_in_the_index_is_said_plainly_without_asking_a_model(built):
    from contextmax import reading

    events = []
    text = "".join(reading.analyse(built, "ollama", "http://127.0.0.1:9", "m", "zzqx wvvy", events.append))
    assert "found nothing in the index" in text and text.endswith("Confidence: Not found")
    assert events == [{"step": "none"}]


def test_contextmax_s_own_confidence_comes_from_what_was_read(built):
    from contextmax import reading

    w = {"key": "A", "file": None, "path": None}
    one = [{"window": w, "held": [{"line": 1, "text": "x"}], "pictured": [], "missing": []}]
    two = one + [{"window": {"key": "B"}, "held": [{"line": 2, "text": "y"}], "pictured": [], "missing": []}]
    assert reading.confidence(built, [], "q")[0] == "Not found"
    assert reading.confidence(built, one, "the pump flow")[0] == "High"              # stated, checked, not contradicted
    assert reading.confidence(built, two, "the pump flow")[0] == "High"
    some = [{"window": w, "held": [{"line": 1, "text": "x"}, {"line": 2, "text": "y"}], "pictured": [], "missing": [{}]}]
    assert reading.confidence(built, some, "q")[0] == "Medium"                       # a quote not in the file
    assert reading.confidence(built, two, "the settle time")[0] == "Medium"          # documents disagree on it
    bad = [{"window": w, "held": [{"line": 1, "text": "x"}], "pictured": [], "missing": [{}, {}]}]
    assert reading.confidence(built, bad, "q")[0] == "Low"


def test_the_source_is_the_truth_for_every_ai(built):
    from contextmax import agentskill, assistants, reading

    w = {"cite": "Detailed design · Design · line 8", "key": "Detailed_design_v2.1"}
    msgs = reading.answer_messages(built, "settle time", [{"window": w, "says": "12 ms", "pictured": [],
                                                           "held": [{"line": 8, "text": "settle time: 12 ms"}]}])
    assert "checked against the file" in msgs[0]["content"] and "Confidence: High" in msgs[0]["content"]
    assert 'line 8: "settle time: 12 ms"' in msgs[1]["content"] and "1~4" in msgs[0]["content"]
    skill = agentskill.compose(built)
    assert "## The source is the truth" in skill and "## End every answer with its confidence" in skill
    assert "**Not found**" in skill and "Never fill a gap with a guess" in skill
    assert "Confidence: High" in assistants.GUIDE and "read it, answer from it and link it" in assistants.GUIDE


def test_only_suggested_models_are_downloaded_and_the_suggestion_fits_the_pc(monkeypatch):
    assert ask.suggested("qwen3.8:27b") and not ask.suggested("qwen3:8b && calc")
    monkeypatch.setattr(ask, "graphics_memory_gb", lambda: 24.0)
    monkeypatch.setattr(ask, "system_memory_gb", lambda: 64.0)
    assert ask.local_models([], True)["suggest"]["model"] == "qwen3.8:27b"
    monkeypatch.setattr(ask, "graphics_memory_gb", lambda: 0.0)
    monkeypatch.setattr(ask, "system_memory_gb", lambda: 16.0)
    local = ask.local_models([], False)
    assert local["suggest"]["model"] == "qwen3:8b" and not local["ollama_installed"] and local["download"].startswith("https://ollama.com")


# == the text cache keeps recognised scans when the PDF reader changes ==

def test_a_recognised_scan_is_kept_when_only_the_pdf_reader_changes(built, tmp_path, monkeypatch):
    from contextmax.docs import textcache

    index = built.documents_dir / "text-index.jsonl"
    keep_index = index.read_bytes()
    rows = util.load_jsonl(index)
    pdf = next(r for r in rows if r["ext"] == ".pdf")
    text = built.documents_dir / pdf["cached_text"]
    keep_text = text.read_bytes()
    try:
        pdf.update(method="ocr", ocr_version=99, reader_version=2)       # recognised by an earlier ContextMAX
        pdf.pop("page_lines", None)
        text.write_text("recognised text", encoding="utf-8")
        pdf["sha256"] = util.hash_file(text)
        util.save_jsonl(index, rows)
        monkeypatch.setattr(textcache.recognition, "OCR_VERSION", 99)
        textcache.build(built, ocr=False)
        again = next(r for r in util.load_jsonl(index) if r["key"] == pdf["key"])
        assert again["method"] == "ocr" and text.read_text(encoding="utf-8") == "recognised text"
        assert util.load_json(built.documents_dir / "text-coverage.json")["ocr_unpaged_count"] == 1
    finally:
        index.write_bytes(keep_index)
        text.write_bytes(keep_text)
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_the_demo_button_opens_the_made_up_project_and_never_writes_it_twice(built):
    from contextmax import panel

    before = (built.workspace / "project.json").stat().st_mtime_ns
    st = panel.Handler._act(None, "demo", {})
    assert st["project"]["slug"] == "demo-project" == built.slug
    assert (built.workspace / "project.json").stat().st_mtime_ns == before
