"""An installer for a PC without internet, made on a PC with internet.

    contextmax offline-installer --source <ContextMAX folder> [--out <folder>]
    (make-offline-installer.cmd runs it)

The result, <out>\\ContextMAX-<version>-offline.zip, holds the program and a wheels folder with:
  - the official Python that setup.cmd would download: the same file, checked against the same SHA-256;
  - every package ContextMAX needs and ContextMAX itself, as wheels for that Python, each pinned with its
    SHA-256 in requirements-lock.txt, so the PC without internet builds nothing and checks every file;
  - RapidOCR's Cyrillic model in wheels\\models, checked against its SHA-256;
  - THIRD-PARTY.txt: each package with its licence, and where the source of the LGPL parts is.
setup.cmd finds the wheels folder and installs from it alone. Before the zip is written, the bundle is
installed once into a scratch folder with the network shut off, so a bundle that would not install
never leaves this PC.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

from contextmax import util
from contextmax.docs import ocr

PLATFORM = "win_amd64"                      # the private Python is the 64-bit Windows build
# what the zip carries of the ContextMAX folder: the program, never a checkout's or a build's leftovers
PROGRAM = ("src", "third_party", "LICENSE", "NOTICE", "README.md", "CHANGELOG.md", "pyproject.toml", "setup.cmd",
           "ContextMAX.cmd", "make-offline-installer.cmd")
NO_NETWORK = {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
              "NO_PROXY": "", "PIP_NO_INDEX": "1"}
# parts of the wheels that are under the LGPL, and where their source is (LGPL-2.1, sections 4 and 6)
LGPL_PARTS = {
    "shapely": "GEOS (LGPL-2.1), the geos*.dll files in shapely.libs: source at https://github.com/libgeos/geos "
               "(the version is in the wheel's LICENSE_GEOS and in shapely's release notes)",
    "opencv_python_headless": "FFmpeg (LGPL-2.1), cv2/opencv_videoio_ffmpeg*.dll: source and build scripts as "
                              "named in the wheel's LICENSE-3RD-PARTY.txt (https://github.com/opencv/opencv-python)",
}
README = """ContextMAX {version}, offline installer

Double-click setup.cmd. Everything it needs is in the wheels folder: no internet is needed, and no
administrator rights. It installs ContextMAX for this Windows user, with a Start menu and desktop
shortcut, the contextmax command and an entry in Settings > Apps.

Made with the official Python {python} for 64-bit Windows (wheels\\python.{python}.nupkg,
SHA-256 {sha256}), the packages listed in wheels\\requirements-lock.txt, each with its SHA-256 (ContextMAX
itself among them), and RapidOCR's Cyrillic text recognition model (wheels\\models). Each package's
licence is listed in wheels\\THIRD-PARTY.txt; the wheels carry their licence files.

RapidOCR needs the Microsoft Visual C++ 2015-2022 runtime, which almost every Windows PC has. If
ContextMAX's check reports that it is missing, an administrator installs vc_redist.x64.exe from
Microsoft; until then scanned PDFs are read by Windows' own text recognition, where it has a language.
"""


class BundleError(Exception):
    pass


def setup_values(source: Path) -> dict:
    """PYVER and PYSHA256 as setup.cmd sets them: one place decides which Python ContextMAX uses."""
    text = (source / "setup.cmd").read_text(encoding="ascii")
    values = dict(re.findall(r'^set "(PYVER|PYSHA256)=([^"%]+)"\r?$', text, re.M))
    if set(values) != {"PYVER", "PYSHA256"}:
        raise BundleError(f"{source / 'setup.cmd'} does not set PYVER and PYSHA256")
    return values


def _clean_env(extra: dict | None = None) -> dict:
    """This process's environment without anything that would make a Python import another ContextMAX."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env.update(PYTHONIOENCODING="utf-8", **(extra or {}))
    return env


def _run(cmd: list, what: str, env: dict | None = None) -> str:
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, encoding="utf-8", errors="replace",
                           env=env or dict(os.environ, PYTHONIOENCODING="utf-8"))
    except FileNotFoundError as exc:
        raise BundleError(f"{what} failed: {cmd[0]} is not on this PC") from exc
    if r.returncode:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-12:])
        raise BundleError(f"{what} failed:\n{tail}")
    return r.stdout


def _copy_program(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True)
    for name in PROGRAM:
        item = source / name
        if item.is_dir():
            shutil.copytree(item, dest / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        elif item.is_file():
            shutil.copy2(item, dest / name)
        elif name in ("src", "pyproject.toml", "setup.cmd"):
            raise BundleError(f"{item} is missing")


def _fetch_python(values: dict, target: Path) -> None:
    """The same download as setup.cmd's, with curl (it uses the certificates Windows trusts)."""
    version, sha256 = values["PYVER"], values["PYSHA256"].lower()
    url = os.environ.get("CONTEXTMAX_PYTHON_URL") or \
        f"https://api.nuget.org/v3-flatcontainer/python/{version}/python.{version}.nupkg"
    if not (target.exists() and util.hash_file(target) == sha256):
        util.say("offline", f"downloading Python {version} (15 MB)")
        _run(["curl.exe", "-fsSL", "--retry", "2", "--connect-timeout", "20", "-y", "60", "-Y", "1024", "-o", target,
              url], "the Python download (this needs internet)")
    if util.hash_file(target) != sha256:
        target.unlink()
        raise BundleError("the Python download does not match the SHA-256 in setup.cmd")


def _download(requirements: list[str], dest: Path, version: str) -> list[Path]:
    """Wheels only, for the private Python on 64-bit Windows, whatever Python runs this."""
    major, minor = version.split(".")[:2]
    before = set(dest.glob("*"))
    _run([sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:",
          "--platform", PLATFORM, "--python-version", f"{major}.{minor}", "--implementation", "cp",
          "--abi", f"cp{major}{minor}", "-d", dest, *requirements],
         "downloading the packages (this needs internet)")
    return sorted(set(dest.glob("*")) - before)


def _own_wheel(bundle: Path, dest: Path) -> Path:
    """ContextMAX built once, here, into a wheel: the PC without internet then builds nothing."""
    before = set(dest.glob("contextmax-*.whl"))
    _run([sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps", "-w", dest, bundle],
         "building ContextMAX's wheel (this needs internet for its build tools)")
    shutil.rmtree(bundle / "build", ignore_errors=True)
    made = sorted(set(dest.glob("contextmax-*.whl")) - before)
    if len(made) != 1:
        raise BundleError(f"building ContextMAX's wheel gave {len(made)} wheels")
    return made[0]


def lock_lines(wheels: list[Path]) -> list[str]:
    """name==version --hash=sha256:... for each wheel (the wheel's file name carries both)."""
    lines = []
    for w in wheels:
        if w.suffix != ".whl":
            raise BundleError(f"not a wheel: {w.name}")
        name, version = w.name.split("-")[:2]
        lines.append(f"{name}=={version} --hash=sha256:{util.hash_file(w)}")
    return sorted(lines, key=str.lower)


def third_party(wheels: list[Path]) -> str:
    """Each wheel's name, version and licence as its metadata states it, and the LGPL parts' sources."""
    rows, notes = [], []
    for w in sorted(wheels, key=lambda p: p.name.lower()):
        name, version = w.name.split("-")[:2]
        licence = "see the licence files in the wheel"
        with zipfile.ZipFile(w) as z:
            meta = next((n for n in z.namelist() if n.endswith(".dist-info/METADATA")), None)
            if meta:
                fields = z.read(meta).decode("utf-8", "replace").split("\n\n", 1)[0].splitlines()
                expression = [f.split(":", 1)[1].strip() for f in fields if f.startswith("License-Expression:")]
                classifiers = [f.split("::")[-1].strip() for f in fields if f.startswith("Classifier: License ::")]
                plain = [f.split(":", 1)[1].strip() for f in fields if f.startswith("License:")]
                choices = expression or ([", ".join(classifiers)] if classifiers else plain[:1])
                licence = (choices[0] if choices else "") or licence
        rows.append(f"  {name} {version}: {licence[:100]}")
        if name.lower() in LGPL_PARTS:
            notes.append(f"  {name}: {LGPL_PARTS[name.lower()]}")
    text = ("Third-party packages in this offline installer (each wheel carries its own licence files)\n\n"
            + "\n".join(rows) + "\n\nPython itself (python.*.nupkg): PSF License Agreement.\n"
            "RapidOCR's models (in the rapidocr wheel and in models): Apache-2.0, see MODEL_LICENSES.md in the wheel.\n")
    if notes:
        text += ("\nParts under the GNU LGPL 2.1, shipped unchanged as separate DLLs inside the wheels named; their\n"
                 "source is available as stated:\n" + "\n".join(notes) + "\n")
    return text


def _check(bundle: Path, nupkg: Path) -> str:
    """Install the bundle into a scratch folder with the network shut off, as setup.cmd does, and make sure
    the ContextMAX that starts is the installed one, not the source this runs from."""
    wheels = bundle / "wheels"
    with tempfile.TemporaryDirectory(prefix="cmx-offline-check-", ignore_cleanup_errors=True) as tmp:
        with zipfile.ZipFile(nupkg) as z:
            z.extractall(tmp, [m for m in z.namelist() if m.startswith("tools/")])
        venv = Path(tmp) / "venv"
        env = _clean_env(NO_NETWORK)
        _run([Path(tmp) / "tools" / "python.exe", "-m", "venv", venv], "making a scratch environment", env)
        py = venv / "Scripts" / "python.exe"
        _run([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--find-links", wheels,
              "--require-hashes", "-r", wheels / "requirements-lock.txt"], "installing the bundle offline", env)
        _run([py, "-m", "contextmax", "ocr-models", "--from", wheels / "models"], "placing the Cyrillic model", env)
        found = _run([py, "-c", "import contextmax, sys; from contextmax.docs import ocr; "
                                "print(contextmax.__file__); print(ocr.rapid_problem() or ocr.rapid_models())"],
                     "starting the installed ContextMAX", env).strip().splitlines()
        if not found or not Path(found[0]).resolve().is_relative_to(venv.resolve()):
            raise BundleError(f"the check did not start the installed ContextMAX ({found[:1]})")
        if "cyrillic" not in found[-1]:
            raise BundleError(f"RapidOCR does not start from the bundle: {found[-1]}")
        return _run([py, "-m", "contextmax", "--version"], "starting the installed ContextMAX", env).strip()


def make(source: Path, out: Path) -> Path:
    source, out = source.resolve(), out.resolve()
    if not (source / "setup.cmd").is_file() or not (source / "pyproject.toml").is_file():
        raise BundleError(f"{source} is not a ContextMAX folder (no setup.cmd and pyproject.toml)")
    if out == source:
        raise BundleError("the zip would go into the ContextMAX folder itself; give it a folder of its own "
                          f"(the default is {source / 'dist'})")
    meta = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
    version = meta["project"]["version"]
    values = setup_values(source)
    name = f"ContextMAX-{version}-offline"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cmx-offline-", ignore_cleanup_errors=True) as tmp:
        bundle = Path(tmp) / name
        util.say("offline", f"copying the program from {source}")
        _copy_program(source, bundle)
        wheels = bundle / "wheels"
        wheels.mkdir()
        nupkg = wheels / f"python.{values['PYVER']}.nupkg"
        cached = source / "wheels" / nupkg.name
        if cached.is_file():
            shutil.copy2(cached, nupkg)
        _fetch_python(values, nupkg)
        util.say("offline", "downloading the packages ContextMAX needs")
        runtime = _download(meta["project"]["dependencies"], wheels, values["PYVER"])
        util.say("offline", "building ContextMAX's own wheel")
        own = _own_wheel(bundle, wheels)
        (wheels / "requirements-lock.txt").write_text("\n".join(lock_lines(runtime + [own])) + "\n", encoding="ascii")
        (wheels / "THIRD-PARTY.txt").write_text(third_party(runtime), encoding="utf-8")
        util.say("offline", "downloading RapidOCR's Cyrillic model")
        try:
            ocr.fetch_models(target=wheels / "models")
        except OSError as exc:
            raise BundleError(str(exc)) from exc
        (bundle / "INSTALL-OFFLINE.txt").write_text(
            README.format(version=version, python=values["PYVER"], sha256=values["PYSHA256"]), encoding="ascii")
        util.say("offline", "installing the bundle once with the network shut off, to check it")
        util.say("offline", f"  {_check(bundle, nupkg)} installs and starts")
        target = out / f"{name}.zip"
        partial = target.with_name(target.name + ".partial")
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
                for f in sorted(bundle.rglob("*")):
                    if f.is_file():
                        z.write(f, f.relative_to(bundle.parent).as_posix())
            os.replace(partial, target)
        except PermissionError as exc:
            raise BundleError(f"{target} is open in another program: close it and run this again") from exc
        except OSError as exc:
            raise BundleError(f"the zip could not be written ({exc})") from exc
        finally:
            partial.unlink(missing_ok=True)
    return target
