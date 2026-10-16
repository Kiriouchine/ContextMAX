"""Small helpers every stage shares: reading, atomic writing, hashing, paths.

Everything that ends up in an output file goes through here, so the rules hold in
one place: UTF-8 without a byte-order mark, LF line endings, a stable key order,
and a write that either lands whole or not at all.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows marks OneDrive files that are not on this disk yet with these bits.
# Opening such a file makes Windows download it, so we look before we read.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
CLOUD_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_RECALL_ON_OPEN


def utc_now() -> str:
    """The one place a clock is read. Callers keep the result out of fingerprints."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_text(path: str | os.PathLike) -> str:
    """Decode a source file the way an editor would: UTF-8 (with or without BOM), else Latin-1."""
    raw = Path(path).read_bytes()
    return decode(raw)


def decode(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def looks_binary(head: bytes) -> bool:
    if not head:
        return False
    if b"\x00" in head:
        return True
    control = sum(1 for b in head if b < 9 or 13 < b < 32)
    return control > len(head) * 0.10


def rel_key(path: str | os.PathLike, root: str | os.PathLike) -> str:
    """A path relative to its root, with forward slashes, the same on every machine."""
    return os.path.relpath(str(path), str(root)).replace("\\", "/")


def is_cloud_placeholder(path: str | os.PathLike) -> bool:
    """True for a OneDrive or SharePoint file whose content is not on this disk yet."""
    if sys.platform != "win32":
        return False
    try:
        attrs = os.stat(path, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    return bool(attrs & CLOUD_MASK)


def is_hidden_or_system(path: str | os.PathLike) -> bool:
    if sys.platform != "win32":
        return Path(path).name.startswith(".")
    try:
        attrs = os.stat(path, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    return bool(attrs & (stat.FILE_ATTRIBUTE_SYSTEM))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str | os.PathLike) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_hash(obj) -> str:
    return sha256_bytes(canonical_json(obj).encode("utf-8"))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def save_text(path: str | os.PathLike, text: str) -> None:
    text = text.replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    _atomic_write_bytes(Path(path), text.encode("utf-8"))


def save_json(path: str | os.PathLike, obj, indent: int | None = 1, sort_keys: bool = False) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=sort_keys)
    save_text(path, text)


def save_jsonl(path: str | os.PathLike, rows) -> int:
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    save_text(path, "\n".join(lines) if lines else "")
    if not lines:
        _atomic_write_bytes(Path(path), b"")
    return len(lines)


def load_json(path: str | os.PathLike, default=None):
    """The parsed file, or `default` when it is missing or not JSON."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def load_jsonl(path: str | os.PathLike) -> list:
    """One record per line; blank lines skipped; a missing file is an empty list."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")       # line ends folded to \n on reading
    except OSError:
        return []
    return [json.loads(line) for line in (raw.strip() for raw in text.split("\n")) if line]


def save_csv(path: str | os.PathLike, header: list[str], rows: list[list]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL)
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    _atomic_write_bytes(Path(path), buf.getvalue().encode("utf-8"))


def csv_rows(path: str | os.PathLike) -> list[dict]:
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


_NOT_LETTER_OR_DIGIT = re.compile(r"[^0-9A-Za-z]+")
_UNSAFE_IN_NAME = re.compile(r"[^-._0-9A-Za-z]+")


def slugify(name: str) -> str:
    return _NOT_LETTER_OR_DIGIT.sub("-", name).strip("-").lower() or "project"


def safe_name(name: str) -> str:
    """A file-name stem made of letters, digits, dot, dash and underscore."""
    return _UNSAFE_IN_NAME.sub("_", name).strip("_") or "doc"


def html_json(obj) -> str:
    """JSON that can sit inside a <script> element without ending it early."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # every < as <: still JSON (unlike <\!--, which made a page with "<!--" in its data show nothing),
    # and neither </script> nor <!-- can end or bend the element
    return s.replace("<", "\\u003c")


def say(stage: str, message: str) -> None:
    print(f"[{stage}] {message}", flush=True)


# The live build: when the ContextMAX window asks for it (CONTEXTMAX_LIVE=1), the build also prints what it
# has found so far, one event per line behind a record separator, for the window to draw. The text lines
# stay as they are, and nothing is written to the working folder, so the index is the same either way.
LIVE_MARK = "\x1e"


def live_on() -> bool:
    return os.environ.get("CONTEXTMAX_LIVE") == "1"


def live(event: str, **data) -> None:
    if live_on():
        print(LIVE_MARK + json.dumps({"e": event, **data}, ensure_ascii=False, separators=(",", ":")), flush=True)
