from __future__ import annotations

import os
import zipfile
from typing import List, Optional


def _extract_zip(src: str, dest: str) -> None:
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # 使用 cp437 以保留日文/中文檔名(encoding fallback)
            name = info.filename
            try:
                data = zf.read(info)
                if name.startswith(("MAC", "__MACOSX")) or ".DS_Store" in name:
                    continue
                target = os.path.join(dest, _decode_name(name))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(data)
            except (OSError, RuntimeError):
                continue


def _decode_name(name: str) -> str:
    """zip filenames are often mis-decoded as cp437; recover UTF-8 names."""
    if any(ord(c) > 0x7f for c in name):
        return name
    try:
        return name.encode("cp437").decode("utf-8")
    except (LookupError, UnicodeEncodeError, UnicodeDecodeError):
        return name


def _extract_7z(src: str, dest: str) -> None:
    try:
        import py7zr
    except ImportError:
        raise RuntimeError("未安裝 py7zr,無法解開 .7z")
    with py7zr.SevenZipFile(src, mode="r") as z:
        z.extractall(path=dest)


def _extract_rar(src: str, dest: str) -> None:
    try:
        import rarfile
    except ImportError:
        raise RuntimeError("未安裝 rarfile,無法解開 .rar")
    with rarfile.RarFile(src) as r:
        r.extractall(path=dest)


def is_archive(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in {".zip", ".7z", ".rar", ".tar", ".gz"}


def extract_archive(src: str, dest: str) -> None:
    ext = os.path.splitext(src)[1].lower()
    os.makedirs(dest, exist_ok=True)
    if ext == ".zip":
        _extract_zip(src, dest)
    elif ext == ".7z":
        _extract_7z(src, dest)
    elif ext == ".rar":
        _extract_rar(src, dest)
    else:
        raise RuntimeError(f"不支援的壓縮格式:{ext}")
