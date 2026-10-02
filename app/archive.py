from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from typing import List, Optional

# 支援之壓縮副檔名
ARCHIVE_EXTS = {".zip", ".7z", ".rar", ".tar", ".gz", ".z", ".iso", ".cab"}


def _candidate_dirs() -> List[str]:
    dirs: List[str] = []
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for b in (base, os.path.dirname(base)):
        for rel in ("7z", "tools/7z", "7zip"):
            dirs.append(os.path.join(b, rel))
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    dirs.append(os.path.join(pf, "7-Zip"))
    dirs.append(os.path.join(pf86, "7-Zip"))
    dirs.append(os.path.join(os.environ.get("ProgramData", ""), "chocolatey", "bin"))
    # WinGet 套件
    winget = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    if os.path.isdir(winget):
        try:
            for entry in os.listdir(winget):
                if "7-zip" in entry.lower() or "7zip" in entry.lower():
                    dirs.append(os.path.join(winget, entry))
        except OSError:
            pass
    return dirs


def find_7z() -> Optional[str]:
    """偵測系統 7-Zip 的 7z.exe(7zfm 亦可)。"""
    for name in ("7z", "7zz", "7zG"):
        found = shutil.which(name)
        if found:
            return found
    # 常見安裝位置直接找 7z.exe
    for d in _candidate_dirs():
        if not os.path.isdir(d):
            continue
        for exe in ("7z.exe", "7zz.exe"):
            cand = os.path.join(d, exe)
            if os.path.isfile(cand):
                return cand
    return None


def _extract_zip(src: str, dest: str) -> None:
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            try:
                data = zf.read(info)
                if name.startswith(("MAC", "__MACOSX")) or ".DS_Store" in name:
                    continue
                # 0x800 = UTF-8 flag; 未標 flag 時 Python 已用 cp437 誤解 CJK,需回轉還原
                is_utf8 = bool(info.flag_bits & 0x800)
                target = os.path.join(dest, _decode_name(name, is_utf8))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(data)
            except (OSError, RuntimeError):
                continue


def _plausible(s: str) -> bool:
    """排除會產生 C1 控制字元/NUL 的解碼結果(正常 CJK 檔名不會有)。"""
    return not any(ord(c) < 0x20 or 0x80 <= ord(c) <= 0x9f for c in s)


def _decode_name(name: str, is_utf8: bool) -> str:
    """zip 檔名還原。

    - UTF-8 flag 已設定:Python 已正確解開,原樣回傳。
    - 未設 flag:Python 用 cp437 誤解(cp437 對 0x00–0xFF 雙射,可精確還原
      原始位元組),再依候選編碼解回:純 ASCII 原樣、UTF-8、Big5(繁體)、
      cp932(日文)、gb18030(簡中)。全部失敗才退回原字串。
    """
    if is_utf8:
        return name
    if not any(ord(c) > 0x7f for c in name):
        return name  # 純 ASCII 不需還原
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for enc in ("utf-8", "big5", "cp932", "gb18030"):
        try:
            s = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if _plausible(s):
            return s
    return name


def _extract_with_7z(seven_z: str, src: str, dest: str) -> None:
    cmd = [seven_z, "x", f"-o{dest}", "-y", "-bb1",
           "-snl", src]  # -snl: 保留長檔名; -bb1: 少量進度
    proc = subprocess.run(
        cmd, capture_output=True, encoding="utf-8", errors="replace",
        shell=False, timeout=3600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"7-Zip 解開失敗 (code {proc.returncode}):"
                           f" {(proc.stderr or proc.stdout).strip()[:200]}")


def is_archive(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in ARCHIVE_EXTS


def extract_archive(src: str, dest: str) -> None:
    ext = os.path.splitext(src)[1].lower()
    os.makedirs(dest, exist_ok=True)
    if ext == ".zip":
        # 內建解開(最快、無外部依賴)
        _extract_zip(src, dest)
        return
    if ext in (".7z", ".rar", ".tar", ".gz", ".z"):
        seven_z = find_7z()
        if not seven_z:
            raise RuntimeError("找不到 7-Zip(無法解開此壓縮檔)。請安裝 7-Zip 或改將內容解開後再選取資料夾。")
        _extract_with_7z(seven_z, src, dest)
        return
    if ext in ARCHIVE_EXTS:
        seven_z = find_7z()
        if not seven_z:
            raise RuntimeError(f"找不到 7-Zip,無法解開 {ext}")
        _extract_with_7z(seven_z, src, dest)
        return
    raise RuntimeError(f"不支援的壓縮格式:{ext}")
