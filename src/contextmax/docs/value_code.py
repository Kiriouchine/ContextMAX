"""Values in the documents held against the named numbers in the code (code/<base>/values.jsonl).

A document's value name meets a code name when they say the same words: "settle time" and
PID_SETTLE_TIME_MS (the code may add one word, such as its module), or when the code's comment is the name
and at most its unit ("#define T_SET 12 /* settle time [ms] */"). Abbreviations are read out (MAX, FREQ, CLK, TEMP); a unit at the
end of a code name is a unit, not a word. A name of one word never matches: "gain" is everywhere. When one
document name meets several code names, every one is listed as a candidate and says so.

Each pair is then compared in one unit:
  match         the same value (a range in the documents holds the code's value; a limit is kept)
  mismatch      a different value, both units known and of one kind
  unit unknown  the code (or the document) does not say its unit; the numbers are still compared, and the
                note says whether the code's number would match in another unit of the same kind
  units differ  the units measure different things (ms against V): most likely not the same value
Everything is recomputed by the document map's gate.
"""
from __future__ import annotations

import decimal
import math
import re
from collections import defaultdict

from contextmax import util
from contextmax.code.values import NAME_UNITS, name_words
from contextmax.docs import params as P

FORMAT_VERSION = 1
_ABBREVIATIONS = {
    "max": "maximum", "min": "minimum", "freq": "frequency", "frq": "frequency", "temp": "temperature",
    "volt": "voltage", "volts": "voltage", "curr": "current", "cnt": "count", "num": "number", "thresh": "threshold",
    "thr": "threshold", "lim": "limit", "spd": "speed", "pos": "position", "vel": "velocity", "accel": "acceleration",
    "acc": "acceleration", "err": "error", "tol": "tolerance", "init": "initial", "def": "default", "dflt": "default",
    "nom": "nominal", "ref": "reference", "clk": "clock", "bw": "bandwidth", "dur": "duration", "tmo": "timeout",
    "pwr": "power", "batt": "battery", "res": "resolution", "len": "length", "dist": "distance", "ang": "angle",
    "avg": "average", "samp": "sample", "smpl": "sample", "dly": "delay", "intvl": "interval", "rx": "receive",
    "tx": "transmit", "cfg": "config", "sp": "setpoint", "kp": "proportional gain", "ki": "integral gain",
    "kd": "derivative gain",
}
_SKIP_WORDS = frozenset("the a an of in for at to on and per by with its is value".split())
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
# each unit as (kind, factor to the kind's base, exact): a factor with pi is compared at the precision written
_UNIT_SCALE = {
    "s": ("time", "1"), "ms": ("time", "1e-3"), "us": ("time", "1e-6"), "ns": ("time", "1e-9"),
    "min": ("time", "60"), "h": ("time", "3600"),
    "Hz": ("frequency", "1"), "kHz": ("frequency", "1e3"), "MHz": ("frequency", "1e6"), "GHz": ("frequency", "1e9"),
    "V": ("voltage", "1"), "mV": ("voltage", "1e-3"), "kV": ("voltage", "1e3"), "uV": ("voltage", "1e-6"),
    "A": ("current", "1"), "mA": ("current", "1e-3"), "uA": ("current", "1e-6"),
    "W": ("power", "1"), "mW": ("power", "1e-3"), "kW": ("power", "1e3"),
    "m": ("length", "1"), "mm": ("length", "1e-3"), "cm": ("length", "1e-2"), "km": ("length", "1e3"),
    "um": ("length", "1e-6"), "nm": ("length", "1e-9"),
    "deg": ("angle", "1"), "rad": ("angle", None),
    "rpm": ("turn rate", "1"), "rad/s": ("turn rate", None), "°/s": ("turn rate", None),
    "Pa": ("pressure", "1"), "kPa": ("pressure", "1e3"), "MPa": ("pressure", "1e6"), "mbar": ("pressure", "1e2"),
    "bar": ("pressure", "1e5"),
    "ohm": ("resistance", "1"), "kΩ": ("resistance", "1e3"),
    "g": ("mass", "1e-3"), "kg": ("mass", "1"), "mg": ("mass", "1e-6"),
    "N": ("force", "1"), "kN": ("force", "1e3"), "Nm": ("torque", "1"), "mNm": ("torque", "1e-3"),
    "uH": ("inductance", "1e-6"), "mH": ("inductance", "1e-3"), "nH": ("inductance", "1e-9"),
    "m/s": ("speed", "1"), "mm/s": ("speed", "1e-3"),
    "%": ("percent", "1"), "°C": ("temperature", "1"), "dB": ("decibel", "1"), "ppm": ("ppm", "1"),
    "bits": ("bits", "1"), "bytes": ("bytes", "1"), "counts": ("counts", "1"),
}
_IRRATIONAL = {"rad": math.degrees(1), "rad/s": 60 / (2 * math.pi), "°/s": 1 / 6}       # in deg, in rpm, in rpm
_LOWER = re.compile(r"(?:at\s+least|minimum(?:\s+of)?|min\.?|no\s+less\s+than|not\s+less\s+than|more\s+than|greater\s+than"
                    r"|above|over|exceed(?:s|ing)?|>=?|≥)\s*$", re.I)
_UPPER = re.compile(r"(?:at\s+most|maximum(?:\s+of)?|max\.?|no\s+more\s+than|not\s+more\s+than|not\s+(?:to\s+)?exceed(?:ing)?"
                    r"|up\s+to|less\s+than|below|under|within|<=?|≤)\s*$", re.I)


def words_of_label(label_norm: str) -> tuple[str, ...]:
    words = re.findall(r"[a-z0-9]+", _BRACKETS.sub(" ", label_norm or ""))
    if words and words[-1] in NAME_UNITS and len(words) > 1:
        words = words[:-1]
    return tuple(w for w in _expand(words) if w not in _SKIP_WORDS)


def words_of_code(name: str) -> tuple[str, ...]:
    words = name_words(name)
    if len(words) > 1 and words[-1] in NAME_UNITS:
        words = words[:-1]
    return tuple(w for w in _expand(words) if w not in _SKIP_WORDS and len(w) >= 2)


def words_of_comment(comment: str) -> tuple[str, ...]:
    """A comment's words when the comment is a name and at most its unit ("settle time", "PWM frequency [Hz]",
    "sample time in ms"); a comment that says more ("sampling frequency reducing parameter") names nothing."""
    words = re.findall(r"[a-z0-9]+", _BRACKETS.sub(" ", comment.lower()))
    while len(words) > 1 and (words[-1] in NAME_UNITS or words[-1] in _SKIP_WORDS):
        words = words[:-1]
    return tuple(w for w in _expand(words) if w not in _SKIP_WORDS)


def _expand(words) -> list[str]:
    return [x for w in words for x in _ABBREVIATIONS.get(w, w).split()]


def code_rows(proj) -> list[dict]:
    """Every named number of every code base, with the code base it is in."""
    rows = []
    for t in proj.code_targets:
        for r in util.load_jsonl(proj.code_dir / t["name"] / "values.jsonl"):
            rows.append(dict(r, target=t["name"], target_label=t.get("label", t["name"])))
    return rows


def _bound(row: dict) -> str:
    """'min' or 'max' when the document states a limit ("at least 6 dB"), else ''."""
    context = row.get("context") or ""
    cut = context.rfind(row.get("value_as_written") or "\x00")
    before = context[:cut] if cut >= 0 else ""
    return "min" if _LOWER.search(before) else "max" if _UPPER.search(before) else ""


def _decimal(text: str):
    try:
        return decimal.Decimal(text)
    except (decimal.InvalidOperation, ValueError):
        return None


def _in_base(value: decimal.Decimal, unit: str):
    """(kind, value in the kind's base unit, exact?) or None for a unit not in the table."""
    if unit not in _UNIT_SCALE:
        return None
    kind, factor = _UNIT_SCALE[unit]
    if factor is None:
        return kind, value * decimal.Decimal(repr(_IRRATIONAL[unit])), False
    return kind, value * decimal.Decimal(factor), True


def _places(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def _half_step(text: str) -> decimal.Decimal:
    return decimal.Decimal(5).scaleb(-_places(text) - 1)


def _fmt(d: decimal.Decimal) -> str:
    return P.canon_number(format(d.normalize(), "f"))


def compare(doc_value: str, doc_unit: str, bound: str, code_value: str, code_unit: str) -> tuple[str, str]:
    """(outcome, note) for one document value against one code value."""
    lo_hi = [_decimal(p) for p in doc_value.split(P.RANGE_MARK)]
    code = _decimal(code_value)
    if code is None or any(x is None for x in lo_hi):
        return "unit unknown", "not a plain number"
    lo, hi = lo_hi[0], lo_hi[-1]
    shown = f"{doc_value} {doc_unit}".strip()
    if not code_unit or not doc_unit:
        same = lo <= code <= hi
        note = f"the code's {code_value} has no unit" if not code_unit else f"the document's {shown} has no unit"
        if same:
            return "unit unknown", note + "; the numbers are the same"
        if not code_unit and doc_unit in _UNIT_SCALE:
            kind = _UNIT_SCALE[doc_unit][0]
            fits = [u for u, (k, f) in sorted(_UNIT_SCALE.items()) if k == kind and f and u != doc_unit
                    and _equal_in(code, u, lo, hi, doc_unit, doc_value)]
            if fits:
                return "unit unknown", note + f"; it would match if it were in {fits[0]}"
        return "unit unknown", note + "; the numbers differ"
    a, b = _in_base(code, code_unit), _in_base(lo, doc_unit)
    if a is None or b is None:
        if code_unit == doc_unit:
            return _verdict(lo <= code <= hi, bound, code < lo, code > hi, shown, f"{code_value} {code_unit}")
        return "units differ", f"{code_unit} in the code, {doc_unit} in the document: no common scale known"
    if a[0] != b[0]:
        return "units differ", f"{code_unit} ({a[0]}) in the code, {doc_unit} ({b[0]}) in the document"
    c_base, lo_base, hi_base = a[1], b[1], _in_base(hi, doc_unit)[1]
    if a[2] and b[2]:
        inside, below, above = lo_base <= c_base <= hi_base, c_base < lo_base, c_base > hi_base
    else:      # a factor with pi: equal at the precision the less precise of the two is written with
        step = max(_in_base(_half_step(code_value), code_unit)[1], _in_base(_half_step(doc_value.split(P.RANGE_MARK)[0]),
                                                                             doc_unit)[1])
        inside = lo_base - step <= c_base <= hi_base + step
        below, above = c_base < lo_base - step, c_base > hi_base + step
    in_doc_unit = _fmt(c_base / _in_base(decimal.Decimal(1), doc_unit)[1]) if code_unit != doc_unit else None
    code_shown = f"{code_value} {code_unit}" + (f" (= {in_doc_unit} {doc_unit})" if in_doc_unit is not None else "")
    return _verdict(inside, bound, below, above, shown, code_shown)


def _equal_in(code, unit, lo, hi, doc_unit, doc_value) -> bool:
    c, low, high = _in_base(code, unit)[1], _in_base(lo, doc_unit)[1], _in_base(hi, doc_unit)[1]
    return low <= c <= high


def _verdict(inside: bool, bound: str, below: bool, above: bool, shown: str, code_shown: str) -> tuple[str, str]:
    if bound == "min":
        ok = not below
        return ("match" if ok else "mismatch"), f"the document asks at least {shown}; the code has {code_shown}"
    if bound == "max":
        ok = not above
        return ("match" if ok else "mismatch"), f"the document allows at most {shown}; the code has {code_shown}"
    if inside:
        return "match", f"{shown} in the document; {code_shown} in the code"
    return "mismatch", f"{shown} in the document; {code_shown} in the code"


def links(value_rows: list[dict], code: list[dict]) -> list[dict]:
    """Every document value name that meets a code name, compared: one row per (code value, document value)."""
    by_words: dict[tuple, list[dict]] = defaultdict(list)
    one_more: dict[tuple, list[dict]] = defaultdict(list)
    for c in code:
        ws = words_of_code(c["name"])
        if len(ws) >= 2:
            by_words[tuple(sorted(ws))].append(c)
        if len(ws) >= 3:
            for k in range(len(ws)):
                one_more[tuple(sorted(ws[:k] + ws[k + 1:]))].append(c)
    said: dict[tuple, list[dict]] = defaultdict(list)          # comments that are a name, and at most its unit
    for c in code:
        cw = words_of_comment(c.get("comment") or "")
        if len(cw) >= 2:
            said[tuple(sorted(cw))].append(c)
    # the document values: per name, per value and unit, the documents that state it (their first place)
    names: dict[str, dict] = {}
    for r in value_rows:
        lab = r.get("label_norm") or ""
        if not lab or P.says_nothing(lab) or r["origin"] == "formula_constant" or not P.all_numbers(r["value_norm"]):
            continue
        n = names.setdefault(lab, {"label": r.get("label") or lab, "values": {}})
        key = (r["value_norm"], r["unit_norm"], _bound(r))
        v = n["values"].setdefault(key, {"shown": f"{r['value_shown']} {r['unit']}".strip(), "documents": {}, "words": {}})
        v["documents"].setdefault(r["doc_ref"], {k: r.get(k) for k in (
            "doc_ref", "file_key", "stage", "line_no", "page", "section", "sheet", "cell")})
        # the words around this statement of the value: its document's name, its sentence, its section
        v["words"].setdefault(r["doc_ref"], set()).update(re.findall(r"[a-z0-9]+", " ".join(
            str(r.get(k) or "") for k in ("doc_ref", "sentence", "context", "section")).lower()))
    out = []
    for lab in sorted(names):
        ws = words_of_label(lab)
        if len(ws) < 2:
            continue
        key = tuple(sorted(ws))
        found = [(c, "name") for c in by_words.get(key, [])]
        if not found:
            found = [(c, "name, with one more word in the code") for c in one_more.get(key, [])]
        if not found:
            found = [(c, "the code's comment") for c in said.get(key, [])]
        if not found:
            continue
        found.sort(key=lambda f: (f[0]["target"], f[0]["file"], f[0]["line"], f[0]["name"]))
        n = names[lab]
        for c, how in found:
            # A numbered name ("control limit 10") is one of a list: met through one more word of the code, the
            # number alone does not make it this part's. That first word names the part (LASER in
            # LASER_CONTROL_LIMIT_10), so the document's name, sentence or section must say it too: "control limit
            # 10" in an optics budget is another thing.
            cw = words_of_code(c["name"])
            numbered = any(w.isdigit() for w in ws)
            extra = {cw[0]} if numbered and how.startswith("name, with one more") and cw[0] not in ws else set()
            for (value_norm, unit_norm, bound), v in sorted(n["values"].items()):
                docs = [v["documents"][k] for k in sorted(v["documents"]) if extra <= v["words"][k]]
                if not docs:
                    continue
                outcome, note = compare(value_norm, unit_norm, bound, c["value_norm"], c["unit"])
                out.append({
                    "label_norm": lab, "label": n["label"], "doc_value": value_norm, "doc_unit": unit_norm,
                    "doc_shown": v["shown"], "bound": bound, "documents": docs, "documents_count": len(docs),
                    "code": {k: c.get(k) for k in ("target", "target_label", "file", "line", "name", "value", "unit",
                                                   "unit_from", "unit_note", "comment", "module", "lang")},
                    "matched_by": how, "candidates_count": len(found), "outcome": outcome, "note": note})
    return out + _by_number(value_rows, code)


def _stem(word: str) -> str:
    for end in ("ing", "ed", "es", "s", "e"):
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[:-len(end)]
    return word


def _by_number(value_rows: list[dict], code: list[dict]) -> list[dict]:
    """A value with no name meets a code value with the same number, in units that measure the same thing
    and convert exactly, when its sentence says at least two words of the code's name ("The sensor shall
    be sampled at 2000 Hz" and SENSOR_SAMPLE_HZ = 2000). It can only confirm: the numbers are equal."""
    at: dict[tuple, list[dict]] = defaultdict(list)
    for c in code:
        base = _in_base(_decimal(c["value_norm"]) or decimal.Decimal(0), c["unit"]) if c.get("unit") else None
        stems = {_stem(w) for w in words_of_code(c["name"])}
        if base and base[2] and len(stems) >= 2:
            at[(base[0], _fmt(base[1]))].append((c, stems))
    pairs: dict[tuple, dict] = {}
    for r in value_rows:
        if r.get("label_norm") or r["origin"] != "prose_value" or r["kind"] != "value" or not r.get("unit_norm"):
            continue
        number = _decimal(r["value_norm"])
        base = _in_base(number, r["unit_norm"]) if number is not None else None
        if not base or not base[2]:
            continue
        said = {_stem(w) for w in re.findall(r"[a-z0-9]+", (r.get("sentence") or r.get("context") or "").lower())}
        same = at.get((base[0], _fmt(base[1])), [])
        for c, stems in same:
            if len(stems & said) < 2:
                continue
            key = (r["value_norm"], r["unit_norm"], c["target"], c["file"], c["line"], c["name"])
            p = pairs.setdefault(key, {"shown": f"{r['value_shown']} {r['unit']}".strip(), "sentence": r.get("sentence"),
                                       "code": c, "words": sorted(stems & said), "documents": {},
                                       "candidates": len(same)})
            p["documents"].setdefault(r["doc_ref"], {k: r.get(k) for k in (
                "doc_ref", "file_key", "stage", "line_no", "page", "section", "sheet", "cell")})
    out = []
    for key in sorted(pairs):
        p, c = pairs[key], pairs[key]["code"]
        outcome, note = compare(key[0], key[1], "", c["value_norm"], c["unit"])
        docs = [p["documents"][k] for k in sorted(p["documents"])]
        out.append({
            "label_norm": "", "label": "", "doc_value": key[0], "doc_unit": key[1], "doc_shown": p["shown"],
            "doc_sentence": p["sentence"], "bound": "", "documents": docs, "documents_count": len(docs),
            "code": {k: c.get(k) for k in ("target", "target_label", "file", "line", "name", "value", "unit",
                                           "unit_from", "unit_note", "comment", "module", "lang")},
            "matched_by": "the same number, and its sentence says " + ", ".join(p["words"]),
            "candidates_count": p["candidates"],
            "outcome": outcome, "note": note})
    return out


def summary(rows: list[dict]) -> dict:
    counts = defaultdict(int)
    for r in rows:
        counts[r["outcome"]] += 1
    return {"pairs_count": len(rows), "names_count": len({r["label_norm"] or r["code"]["name"] for r in rows}),
            "outcomes": dict(sorted(counts.items()))}
