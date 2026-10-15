"""ContextMAX as a Windows program for this user: set up by setup.cmd, taken down by uninstall.cmd.

setup.cmd provides Python, the private environment and the packages; this module does the rest,
the same way on every PC:

  <home>\\ContextMAX.cmd     opens the window (the shortcuts start it, minimised)
  <home>\\bin\\contextmax.cmd and cmx.cmd
                            the command line; <home>\\bin goes on the user's PATH and holds only
                            these, so the user's own python and pip stay first
  <home>\\uninstall.cmd      removes the program and keeps the projects
  Start menu and desktop    a "ContextMAX" shortcut each
  Apps & features           an entry with ContextMAX's version and an Uninstall button
  contextmax-open: links    "Open document" and "Show in folder" on a page opened from disk

Everything is per user, without administrator rights, and undone by `uninstall`.
"""
from __future__ import annotations

import ctypes
import os
import winreg
from datetime import date
from pathlib import Path

from contextmax import VERSION, project

APP = "ContextMAX"
ENV_KEY = "Environment"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ContextMAX"
LINK_KEY = r"Software\Classes\contextmax-open"      # pages opened from disk open files through this (opener.py)
ICON = Path(__file__).resolve().parent / "views" / "assets" / "contextmax.ico"
MARKER = "contextmax-program.txt"            # in the ContextMAX folder: uninstall.cmd removes only where it is
RUNTIME_MARKER = "contextmax-runtime.txt"    # in the private Python folder, written by setup.cmd


def launcher_texts(home: Path) -> dict[Path, str]:
    """The launchers find the private environment from where they are (%~dp0), so they hold no folder
    name: cmd reads a .cmd file in the console's code page, which would garble a name with é or я."""
    in_home = '"%~dp0.venv\\Scripts\\python.exe"'
    in_bin = '"%~dp0..\\.venv\\Scripts\\python.exe"'
    return {
        home / "ContextMAX.cmd": (
            "@echo off\r\n"
            "rem Opens the ContextMAX window. Written by setup.cmd: run setup.cmd again to update ContextMAX.\r\n"
            "rem Close this window to stop ContextMAX.\r\n"
            f"title {APP}\r\n"
            f"{in_home} -m contextmax panel %*\r\n"),
        home / "bin" / "contextmax.cmd": f"@echo off\r\n{in_bin} -m contextmax %*\r\n",
        home / "bin" / "cmx.cmd": f"@echo off\r\n{in_bin} -m contextmax %*\r\n",
        home / "uninstall.cmd": (
            "@echo off\r\n"
            "rem uninstall.cmd: removes the ContextMAX program for this user: its Python, its shortcuts, its\r\n"
            "rem command on the PATH and its entry in Apps & features. Projects and their working folders stay.\r\n"
            "setlocal\r\n"
            'set "CMXDIR=%~dp0"\r\n'
            'if /i "%~1"=="/quiet" goto :remove\r\n'
            'echo This removes the ContextMAX program. Your projects in "%CMXDIR%" stay.\r\n'
            'choice /c YN /m "Remove ContextMAX"\r\n'
            "if errorlevel 2 exit /b 1\r\n"
            ":remove\r\n"
            # only in the folder setup made: a copy of this file elsewhere must not delete folders there
            f'if not exist "%CMXDIR%{MARKER}" (echo This is not a ContextMAX program folder; nothing was removed.& exit /b 1)\r\n'
            'set "CONTEXTMAX_HOME=%CMXDIR:~0,-1%"\r\n'
            'if exist "%CMXDIR%.venv\\Scripts\\python.exe" "%CMXDIR%.venv\\Scripts\\python.exe" -m contextmax uninstall %CONTEXTMAX_UNINSTALL_ARGS%\r\n'
            'cd /d "%TEMP%"\r\n'
            'if exist "%CMXDIR%.venv\\pyvenv.cfg" rmdir /s /q "%CMXDIR%.venv"\r\n'
            # what an update moved aside and could not remove yet (only setup.cmd makes these two names)
            'if exist "%CMXDIR%.venv-old\\" rmdir /s /q "%CMXDIR%.venv-old"\r\n'
            'if exist "%CMXDIR%.python-old\\" rmdir /s /q "%CMXDIR%.python-old"\r\n'
            f'if exist "%CMXDIR%python\\{RUNTIME_MARKER}" rmdir /s /q "%CMXDIR%python"\r\n'
            'if exist "%CMXDIR%bin\\contextmax.cmd" if not exist "%CMXDIR%bin\\project.json" rmdir /s /q "%CMXDIR%bin"\r\n'
            'if exist "%CMXDIR%ContextMAX.cmd" del /q "%CMXDIR%ContextMAX.cmd"\r\n'
            f'del /q "%CMXDIR%{MARKER}" 2>nul\r\n'
            'echo ContextMAX was removed. Your projects are still in "%CMXDIR%"\r\n'
            '(goto) 2>nul & del "%~f0"\r\n'),
    }


def _same_folder(a: str, b: str) -> bool:
    def norm(p: str) -> str:
        return os.path.normcase(os.path.normpath(os.path.expandvars(p.strip().strip('"'))))

    return bool(a.strip().strip('"')) and norm(a) == norm(b)


def _read_path(key_name: str) -> tuple[str | None, int]:
    """The user's Path value and its kind; None when there is no such value."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as key:
            value, kind = winreg.QueryValueEx(key, "Path")
            return str(value), kind
    except FileNotFoundError:
        return None, winreg.REG_EXPAND_SZ


def _delete_path(key_name: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name, 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, "Path")
    _announce_environment()


def _write_path(key_name: str, value: str, kind: int) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_name, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, kind, value)
    _announce_environment()


def _announce_environment() -> None:
    """Tell running programs (Explorer above all) that the user's environment changed."""
    result = ctypes.c_size_t()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 0x2, 3000, ctypes.byref(result))


def add_to_path(folder: Path, key_name: str | None = None) -> bool:
    """Append `folder` to the user's PATH unless it is there; the rest is kept exactly as written, so
    removing it gives the old value back. True when it was added."""
    key_name = key_name or ENV_KEY
    value, kind = _read_path(key_name)
    if value and any(_same_folder(p, str(folder)) for p in value.split(";")):
        return False
    _write_path(key_name, f"{value};{folder}" if value else str(folder), kind)
    return True


def remove_from_path(folder: Path, key_name: str | None = None) -> bool:
    """Remove `folder` from the user's PATH, touching nothing else; an emptied value is deleted."""
    key_name = key_name or ENV_KEY
    value, kind = _read_path(key_name)
    if value is None:
        return False
    parts = value.split(";")
    kept = [p for p in parts if not _same_folder(p, str(folder))]
    if len(kept) == len(parts):
        return False
    rest = ";".join(kept)
    if rest.strip(" ;"):
        _write_path(key_name, rest, kind)
    else:
        _delete_path(key_name)
    return True


def _folder_kb(*folders: Path) -> int:
    total = 0
    for folder in folders:
        for root, _dirs, files in os.walk(folder):
            total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    return total // 1024


def register(home: Path, key_name: str | None = None) -> None:
    """The entry in Apps & features (Settings) for this user."""
    key_name = key_name or UNINSTALL_KEY
    uninstaller = home / "uninstall.cmd"
    values = {
        "DisplayName": (APP, winreg.REG_SZ), "DisplayVersion": (VERSION, winreg.REG_SZ),
        "Publisher": ("Sev Kiriouchine", winreg.REG_SZ), "InstallLocation": (str(home), winreg.REG_SZ),
        "UninstallString": (f'"{uninstaller}"', winreg.REG_SZ),
        "QuietUninstallString": (f'"{uninstaller}" /quiet', winreg.REG_SZ),
        "DisplayIcon": (str(ICON), winreg.REG_SZ),
        "URLInfoAbout": ("https://github.com/Kiriouchine/ContextMAX", winreg.REG_SZ),
        "InstallDate": (date.today().strftime("%Y%m%d"), winreg.REG_SZ),
        "EstimatedSize": (_folder_kb(home / ".venv", home / "python"), winreg.REG_DWORD),
        "NoModify": (1, winreg.REG_DWORD), "NoRepair": (1, winreg.REG_DWORD),
    }
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_name, 0, winreg.KEY_SET_VALUE) as key:
        for name, (value, kind) in values.items():
            winreg.SetValueEx(key, name, 0, kind, value)


def unregister(home: Path, key_name: str | None = None) -> bool:
    """Remove the Apps entry, but only the one that belongs to this ContextMAX folder."""
    key_name = key_name or UNINSTALL_KEY
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as key:
            location = str(winreg.QueryValueEx(key, "InstallLocation")[0])
    except FileNotFoundError:
        return False
    if not _same_folder(location, str(home)):
        return False
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_name)
    return True


def _link_command(home: Path) -> str:
    return f'"{home / ".venv" / "Scripts" / "pythonw.exe"}" -m contextmax link "%1"'


def register_links(home: Path, key_name: str | None = None) -> None:
    """contextmax-open: links, for this user, run `contextmax link` without a console window."""
    key_name = key_name or LINK_KEY
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_name, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:ContextMAX link")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_name + r"\DefaultIcon", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{ICON}",0')
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_name + r"\shell\open\command", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, _link_command(home))


def unregister_links(home: Path, key_name: str | None = None) -> bool:
    """Take the links away, but only when they run this ContextMAX folder's Python."""
    key_name = key_name or LINK_KEY
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name + r"\shell\open\command") as key:
            command = str(winreg.QueryValueEx(key, "")[0])
    except FileNotFoundError:
        return False
    if command != _link_command(home):
        return False
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", r"\DefaultIcon", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_name + sub)
        except FileNotFoundError:
            pass
    return True


def shortcut_paths(start_menu: Path | None = None, desktop: Path | None = None) -> list[Path]:
    from contextmax import winshell

    return [(start_menu or winshell.known_folder("programs")) / f"{APP}.lnk",
            (desktop or winshell.known_folder("desktop")) / f"{APP}.lnk"]


def install(*, shortcuts: bool = True, path: bool = True, apps_entry: bool = True, links: bool = True,
            start_menu: Path | None = None, desktop: Path | None = None, env_key: str | None = None,
            uninstall_key: str | None = None, link_key: str | None = None) -> list[str]:
    """Write the launchers and, as asked, the shortcuts, the PATH entry, the Apps entry and the links."""
    env_key, uninstall_key, link_key = env_key or ENV_KEY, uninstall_key or UNINSTALL_KEY, link_key or LINK_KEY
    from contextmax import winshell

    home = project.default_home().resolve()
    bin_is_a_project = (home / "bin" / "project.json").exists()
    done = []
    for target, text in launcher_texts(home).items():
        if bin_is_a_project and target.parent.name == "bin":
            continue                  # an older project lives in <home>\bin: never write into it
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("ascii"))
        done.append(f"wrote {target}")
    (home / MARKER).write_text(f"ContextMAX {VERSION}: the program installed here by setup.cmd; uninstall.cmd removes it\n",
                               encoding="ascii")
    if shortcuts:
        for lnk in shortcut_paths(start_menu, desktop):
            winshell.make_shortcut(lnk, home / "ContextMAX.cmd", workdir=home, minimized=True, icon=(str(ICON), 0),
                                   description="Maps of a project's code and documents, and the links between them")
            done.append(f"shortcut {lnk}")
    if path and bin_is_a_project:
        done.append(f"not on the PATH: {home / 'bin'} is a project's folder, so the contextmax command was left out")
    elif path:
        added = add_to_path(home / "bin", env_key)
        done.append(f"{'added' if added else 'already on'} the PATH: {home / 'bin'} (a new terminal window sees it)")
    if apps_entry:
        register(home, uninstall_key)
        done.append("listed in Apps & features")
    if links:
        register_links(home, link_key)
        done.append("contextmax-open: links open documents from pages opened from disk")
    return done


def uninstall(*, start_menu: Path | None = None, desktop: Path | None = None, env_key: str | None = None,
              uninstall_key: str | None = None, link_key: str | None = None) -> list[str]:
    """Remove what `install` added outside the ContextMAX folder; uninstall.cmd deletes the rest."""
    env_key, uninstall_key, link_key = env_key or ENV_KEY, uninstall_key or UNINSTALL_KEY, link_key or LINK_KEY
    from contextmax import winshell

    home = project.default_home().resolve()
    done = []

    def step(what: str, action) -> None:
        try:
            result = action()
            if result:
                done.append(result if isinstance(result, str) else what)
        except OSError as exc:              # one step that fails must not stop the others
            done.append(f"could not {what}: {exc}")

    for lnk in shortcut_paths(start_menu, desktop):
        def remove_shortcut(lnk=lnk):
            if lnk.exists() and _same_folder(winshell.read_shortcut(lnk)["target"], str(home / "ContextMAX.cmd")):
                lnk.unlink()
                return f"removed {lnk}"
            return None
        step(f"remove {lnk}", remove_shortcut)
    step(f"remove {home / 'bin'} from the PATH", lambda: remove_from_path(home / "bin", env_key)
         and f"removed {home / 'bin'} from the PATH")
    step("remove the Apps & features entry", lambda: unregister(home, uninstall_key) and "removed from Apps & features")
    step("remove the contextmax-open: links", lambda: unregister_links(home, link_key) and "removed the contextmax-open: links")
    return done
