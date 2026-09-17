# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Units of measure: a small alias table (extended by `documents.units_extra` in the config),
normalisation, label/unit splitting ("gain [1/s]") and the prose quantity pattern.

Short unit symbols (m, s, g, A, V, W, N, K, h) are matched case-sensitively in prose so that
"5 a" or "3 In" never become quantities; long aliases (seconds, degrees) are case-insensitive."""

from __future__ import annotations

import re

# canonical -> aliases (lower-case unless marked case-sensitive by being in SHORT)
CANONICAL: dict[str, tuple[str, ...]] = {
    "s": ("s", "sec", "secs", "second", "seconds"),
    "ms": ("ms", "msec", "millisecond", "milliseconds"),
    "µs": ("µs", "us", "microsecond", "microseconds"),
    "min": ("min", "mins", "minute", "minutes"),
    "h": ("h", "hr", "hrs", "hour", "hours"),
    "Hz": ("hz", "hertz"),
    "kHz": ("khz",),
    "MHz": ("mhz",),
    "GHz": ("ghz",),
    "rad": ("rad", "radian", "radians"),
    "deg": ("deg", "degs", "degree", "degrees", "°"),
    "rad/s": ("rad/s", "rad/sec", "rads"),
    "deg/s": ("deg/s", "deg/sec", "°/s"),
    "m": ("m", "meter", "meters", "metre", "metres"),
    "mm": ("mm", "millimeter", "millimeters", "millimetre", "millimetres"),
    "cm": ("cm", "centimeter", "centimeters", "centimetre", "centimetres"),
    "km": ("km", "kilometer", "kilometers", "kilometre", "kilometres"),
    "m/s": ("m/s", "m/sec", "mps"),
    "m/s^2": ("m/s^2", "m/s2", "m/s²", "m/sec^2"),
    "km/h": ("km/h", "kph", "kmh"),
    "kg": ("kg", "kilogram", "kilograms"),
    "g": ("g", "gram", "grams"),
    "N": ("n", "newton", "newtons"),
    "N·m": ("N·m", "Nm", "N.m", "N*m", "newton-meter", "newton-metre"),
    "nm": ("nm", "nanometer", "nanometers", "nanometre", "nanometres"),
    "V": ("v", "volt", "volts"),
    "mV": ("mv", "millivolt", "millivolts"),
    "A": ("a", "amp", "amps", "ampere", "amperes"),
    "mA": ("ma", "milliamp", "milliamps", "milliampere"),
    "W": ("w", "watt", "watts"),
    "kW": ("kw", "kilowatt", "kilowatts"),
    "Wh": ("wh",),
    "mAh": ("mah",),
    "%": ("%", "percent", "pct"),
    "°C": ("°c", "degc", "celsius"),
    "K": ("k", "kelvin"),
    "dB": ("db", "decibel", "decibels"),
    "rpm": ("rpm",),
    "Pa": ("pa", "pascal", "pascals"),
    "kPa": ("kpa",),
    "bar": ("bar",),
    "J": ("j", "joule", "joules"),
    "Ω": ("Ω", "ohm", "ohms"),
    "px": ("px", "pixel", "pixels"),
    "bit": ("bit", "bits"),
    "byte": ("byte", "bytes"),
    "kB": ("kb", "kib", "kilobyte", "kilobytes"),
    "MB": ("mb", "mib", "megabyte", "megabytes"),
    "GB": ("gb", "gib", "gigabyte", "gigabytes"),
    "baud": ("baud",),
    "samples": ("samples", "sample"),
    "1/s": ("1/s", "s^-1", "s-1"),
}
# Symbols that must match case-sensitively in prose (single letters and near-words).
SHORT = {"s", "m", "g", "N", "V", "A", "W", "K", "h", "J", "a", "v", "w", "k", "n", "ms", "us", "mv", "ma", "mb", "gb", "kb", "min", "bar", "bit"}
UNIT_IN_LABEL = re.compile(r"^(?P<label>.*?)\s*[\[(](?P<unit>[^\[\]()]{1,16})[\])]\s*$")
NUMBER = r"[-+]?(?:\d+(?:[.,]\d+)?|\.\d+)(?:[eE][-+]?\d+)?"


EXACT: dict[str, str] = {alias: canonical for canonical, aliases in CANONICAL.items() for alias in aliases}
EXACT.update({canonical: canonical for canonical in CANONICAL})


def alias_table(extra: list[str] | None = None) -> dict[str, str]:
    """lower-cased alias -> canonical; `extra` entries are `alias=canonical` or bare units."""
    table: dict[str, str] = {}
    for canonical, aliases in CANONICAL.items():
        table[canonical.lower()] = canonical
        for alias in aliases:
            table[alias.lower()] = canonical
    for entry in extra or []:
        alias, _, canonical = entry.partition("=")
        alias = alias.strip()
        canonical = canonical.strip() or alias
        if alias:
            table[alias.lower()] = canonical
    return table


def normalise_unit(raw: str | None, table: dict[str, str] | None = None) -> str | None:
    if not raw:
        return None
    text = raw.strip().strip(".,;:")
    if not text:
        return None
    table = table or alias_table()
    if text in EXACT:  # case-sensitive first: Nm (torque) is not nm (length)
        return EXACT[text]
    return table.get(text.lower(), text)


def split_label_unit(label: str) -> tuple[str, str | None]:
    """'gain [1/s]' -> ('gain', '1/s'); 'mass (kg)' -> ('mass', 'kg'); else (label, None)."""
    m = UNIT_IN_LABEL.match(label.strip())
    if not m:
        return label.strip(), None
    unit = m.group("unit").strip()
    if not unit or len(unit.split()) > 2 or unit.replace(".", "").isdigit():
        return label.strip(), None
    return m.group("label").strip(), unit


def unit_like(text: str, table: dict[str, str] | None = None) -> bool:
    """Whether a short cell text is a unit ('deg', '[m/s]', 'Hz')."""
    stripped = text.strip().strip("[]()")
    if not stripped or len(stripped) > 12 or " " in stripped.strip():
        return False
    table = table or alias_table()
    return stripped in CANONICAL or stripped.lower() in table


def quantity_pattern(extra: list[str] | None = None) -> re.Pattern[str]:
    """`<number><optional space><unit>` with a word boundary after the unit."""
    table = alias_table(extra)
    long_forms = sorted({a for a in table if a not in SHORT and len(a) > 1}, key=len, reverse=True)
    short_forms = sorted({c for c in CANONICAL if c in SHORT or len(c) <= 2} | {"%", "°"}, key=len, reverse=True)
    long_alt = "|".join(re.escape(a) for a in long_forms)
    short_alt = "|".join(re.escape(a) for a in short_forms)
    return re.compile(
        rf"(?<![\w.,-])(?P<num>{NUMBER})\s?(?:(?P<long>(?i:{long_alt}))|(?P<short>{short_alt}))(?![\w/^])"
    )
