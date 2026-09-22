from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import List, Tuple

_FO_DELETE = 3
_FOF_NOCONFIRM = 0x10
_FOF_SILENT = 0x04
_FOF_ALLOWUNDO =  0x40


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HANDLE),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPWSTR),
        ("pTo", wintypes.LPWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPWSTR),
    ]


def _trash_one(path: str) -> bool:
    op = _SHFILEOPSTRUCTW()
    op.wFunc = _FO_DELETE
    op.pFrom = path + "\0"
    op.fFlags = _FOF_NOCONFIRM | _FOF_SILENT | _FOF_ALLOWUNDO
    try:
        res = ctypes.windll.shell32.SHFileMoveW(ctypes.byref(op), op)
    except Exception:  # noqa: BLE001
        return False
    return res == 0


def send_to_trash(paths: List[str]) -> Tuple[int, int]:
    """Send paths to the Windows recycle bin. Returns (succeeded, failed)."""
    ok = 0
    fail = 0
    for p in paths:
        if _trash_one(p):
            ok += 1
        else:
            fail += 1
    return ok, fail
