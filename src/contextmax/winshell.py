"""The Windows shell's own folder picker and shortcuts, reached with ctypes alone.

No extra package, no PowerShell and no tkinter (which the private Python that setup.cmd installs
does not have): the folder picker is the dialog File Explorer uses (IFileOpenDialog in folder
mode), and shortcuts are written and read with IShellLinkW. COM methods are called by their place
in the interface's method table, as declared in the Windows SDK (shobjidl_core.h, objidl.h).

    python -m contextmax.winshell pick "<title>"     prints the chosen folder, or nothing if cancelled
"""
from __future__ import annotations

import ctypes
import sys
import threading
import uuid
from ctypes import wintypes
from pathlib import Path

HRESULT = ctypes.c_long
ERROR_CANCELLED = -2147023673          # HRESULT_FROM_WIN32(ERROR_CANCELLED), 0x800704C7
FOS_PICKFOLDERS, FOS_FORCEFILESYSTEM, FOS_PATHMUSTEXIST = 0x20, 0x40, 0x800
SIGDN_FILESYSPATH = 0x80058000
SW_SHOWMINNOACTIVE = 7
STGM_READ = 0

FILE_OPEN_DIALOG = ("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7", "D57C7288-D4AD-4768-BE02-9D969532D960")
SHELL_LINK = ("00021401-0000-0000-C000-000000000046", "000214F9-0000-0000-C000-000000000046")
IID_PERSIST_FILE = "0000010B-0000-0000-C000-000000000046"
KNOWN_FOLDERS = {"programs": "A77F5D77-2E2B-44C3-A6A2-ABA601054A51", "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"}

# Places in the method tables (the three IUnknown methods come first in every one).
_QUERY, _RELEASE = 0, 2
_DLG_SHOW, _DLG_SET_OPTIONS, _DLG_GET_OPTIONS, _DLG_SET_TITLE, _DLG_GET_RESULT = 3, 9, 10, 17, 20
_ITEM_GET_DISPLAY_NAME = 5
_LINK_GET_PATH, _LINK_SET_DESCRIPTION, _LINK_GET_WORKDIR, _LINK_SET_WORKDIR = 3, 7, 8, 9
_LINK_GET_ARGUMENTS, _LINK_SET_ARGUMENTS, _LINK_GET_SHOW, _LINK_SET_SHOW = 10, 11, 14, 15
_LINK_SET_ICON, _LINK_SET_PATH = 17, 20
_FILE_LOAD, _FILE_SAVE = 5, 6


class _GUID(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_ulong), ("data2", ctypes.c_ushort), ("data3", ctypes.c_ushort),
                ("data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    g = _GUID()
    ctypes.memmove(ctypes.byref(g), uuid.UUID(text).bytes_le, 16)
    return g


def _check(hr: int) -> None:
    if hr < 0:
        raise OSError(f"Windows shell call failed: HRESULT 0x{hr & 0xFFFFFFFF:08X}")


class _Interface:
    """One COM interface pointer."""

    def __init__(self, pointer: ctypes.c_void_p):
        self.pointer = pointer

    def call(self, index: int, *args, argtypes: tuple = (), restype=HRESULT):
        table = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        method = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])
        return method(self.pointer, *args)

    def query(self, iid: str) -> _Interface:
        out = ctypes.c_void_p()
        _check(self.call(_QUERY, ctypes.byref(_guid(iid)), ctypes.byref(out), argtypes=(ctypes.c_void_p, ctypes.c_void_p)))
        return _Interface(out)

    def release(self) -> None:
        if self.pointer:
            self.call(_RELEASE, restype=ctypes.c_ulong)
            self.pointer = None


def _create(clsid_iid: tuple[str, str]) -> _Interface:
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, 0x2 | 0x4)              # apartment threaded, no OLE1 DDE; repeat calls are harmless
    out = ctypes.c_void_p()
    clsid, iid = clsid_iid
    _check(ole32.CoCreateInstance(ctypes.byref(_guid(clsid)), None, 1, ctypes.byref(_guid(iid)), ctypes.byref(out)))
    return _Interface(out)


def _work_area() -> wintypes.RECT:
    user32 = ctypes.windll.user32
    area = wintypes.RECT()
    if not user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0):      # SPI_GETWORKAREA
        area = wintypes.RECT(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    return area


def _owner_window() -> int:
    """A hidden, always-on-top window over the screen's work area: the dialog it owns opens in front
    of the browser that asked for it, and at the top left of that area until it is centred."""
    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    area = _work_area()
    return user32.CreateWindowExW(0x8 | 0x80, "STATIC", "ContextMAX", 0x80000000, area.left, area.top,
                                  area.right - area.left, area.bottom - area.top, None, None, None, None)


def _centre_when_shown(owner: int, title: str, stop: threading.Event) -> None:
    """The dialog opens at its owner's top left corner; move it to the middle of the work area as soon
    as it shows. Runs beside Show(), whose message loop handles the move."""
    user32 = ctypes.windll.user32
    user32.FindWindowExW.restype = user32.GetWindow.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    while not stop.wait(0.02):
        hwnd = None
        while hwnd := user32.FindWindowExW(None, hwnd, "#32770", title):       # the dialogs with this title
            if user32.GetWindow(hwnd, 4) == owner and user32.IsWindowVisible(hwnd):      # GW_OWNER
                box, area = wintypes.RECT(), _work_area()
                user32.GetWindowRect(hwnd, ctypes.byref(box))
                x = area.left + max(0, (area.right - area.left - (box.right - box.left)) // 2)
                y = area.top + max(0, (area.bottom - area.top - (box.bottom - box.top)) // 2)
                user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x1 | 0x4 | 0x10)    # no size, z-order or activation change
                return


def pick_folder(title: str) -> str:
    """The chosen folder, or "" when the dialog is cancelled."""
    dialog = _create(FILE_OPEN_DIALOG)
    owner = _owner_window()
    stop = threading.Event()
    if owner:
        threading.Thread(target=_centre_when_shown, args=(owner, title, stop), daemon=True).start()
    try:
        options = wintypes.DWORD()
        _check(dialog.call(_DLG_GET_OPTIONS, ctypes.byref(options), argtypes=(ctypes.c_void_p,)))
        _check(dialog.call(_DLG_SET_OPTIONS, options.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST,
                           argtypes=(wintypes.DWORD,)))
        _check(dialog.call(_DLG_SET_TITLE, title, argtypes=(wintypes.LPCWSTR,)))
        shown = dialog.call(_DLG_SHOW, owner, argtypes=(wintypes.HWND,))
        if shown == ERROR_CANCELLED:
            return ""
        _check(shown)
        result = ctypes.c_void_p()
        _check(dialog.call(_DLG_GET_RESULT, ctypes.byref(result), argtypes=(ctypes.c_void_p,)))
        item = _Interface(result)
        try:
            text = ctypes.c_void_p()
            _check(item.call(_ITEM_GET_DISPLAY_NAME, SIGDN_FILESYSPATH, ctypes.byref(text),
                             argtypes=(wintypes.DWORD, ctypes.c_void_p)))
            try:
                return ctypes.wstring_at(text)
            finally:
                ctypes.windll.ole32.CoTaskMemFree(text)
        finally:
            item.release()
    finally:
        stop.set()
        dialog.release()
        if owner:
            ctypes.windll.user32.DestroyWindow(owner)


def make_shortcut(lnk: Path, target: Path, arguments: str = "", workdir: Path | None = None, description: str = "",
                  icon: tuple[str, int] | None = None, minimized: bool = False) -> None:
    """Write a .lnk file, replacing one that is there."""
    link = _create(SHELL_LINK)
    try:
        _check(link.call(_LINK_SET_PATH, str(target), argtypes=(wintypes.LPCWSTR,)))
        _check(link.call(_LINK_SET_ARGUMENTS, arguments, argtypes=(wintypes.LPCWSTR,)))
        _check(link.call(_LINK_SET_WORKDIR, str(workdir or Path(target).parent), argtypes=(wintypes.LPCWSTR,)))
        _check(link.call(_LINK_SET_DESCRIPTION, description, argtypes=(wintypes.LPCWSTR,)))
        if icon:
            _check(link.call(_LINK_SET_ICON, icon[0], icon[1], argtypes=(wintypes.LPCWSTR, ctypes.c_int)))
        if minimized:
            _check(link.call(_LINK_SET_SHOW, SW_SHOWMINNOACTIVE, argtypes=(ctypes.c_int,)))
        Path(lnk).parent.mkdir(parents=True, exist_ok=True)
        persist = link.query(IID_PERSIST_FILE)
        try:
            _check(persist.call(_FILE_SAVE, str(lnk), True, argtypes=(wintypes.LPCWSTR, wintypes.BOOL)))
        finally:
            persist.release()
    finally:
        link.release()


def read_shortcut(lnk: Path) -> dict:
    """What a .lnk file starts: target, arguments, working folder and window state."""
    link = _create(SHELL_LINK)
    try:
        persist = link.query(IID_PERSIST_FILE)
        try:
            _check(persist.call(_FILE_LOAD, str(lnk), STGM_READ, argtypes=(wintypes.LPCWSTR, wintypes.DWORD)))
        finally:
            persist.release()
        out = {}
        for key, index, extra in (("target", _LINK_GET_PATH, True), ("arguments", _LINK_GET_ARGUMENTS, False),
                                  ("workdir", _LINK_GET_WORKDIR, False)):
            buf = ctypes.create_unicode_buffer(32768)
            if extra:     # GetPath also takes a WIN32_FIND_DATAW pointer (none wanted) and flags
                _check(link.call(index, buf, len(buf), None, 0,
                                 argtypes=(wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)))
            else:
                _check(link.call(index, buf, len(buf), argtypes=(wintypes.LPWSTR, ctypes.c_int)))
            out[key] = buf.value
        show = ctypes.c_int()
        _check(link.call(_LINK_GET_SHOW, ctypes.byref(show), argtypes=(ctypes.c_void_p,)))
        out["minimized"] = show.value == SW_SHOWMINNOACTIVE
        return out
    finally:
        link.release()


def known_folder(name: str) -> Path:
    """The Start menu's Programs folder or the desktop, wherever this user's are (OneDrive included)."""
    out = ctypes.c_void_p()
    _check(ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(_guid(KNOWN_FOLDERS[name])), 0, None,
                                                      ctypes.byref(out)))
    try:
        return Path(ctypes.wstring_at(out))
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "pick":
        print(pick_folder(sys.argv[2] if len(sys.argv) > 2 else "Choose a folder"))
    else:
        raise SystemExit("usage: python -m contextmax.winshell pick \"<title>\"")
