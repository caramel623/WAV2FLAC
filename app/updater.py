from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

GITHUB_API = "https://api.github.com/repos"
REPO = "caramel623/WAV2FLAC"
_TIMEOUT = 25
_UA = "WAV2FLAC-Updater"
# 更新時用於啟動獨立行程的 Windows 常數
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def _parse_version(v: str) -> tuple:
    digits = []
    for part in (v or "").replace("v", "").strip().split("."):
        num = ""
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        digits.append(int(num) if num else 0)
    while len(digits) < 3:
        digits.append(0)
    return tuple(digits[:3])


def compare_versions(current: str, latest: str) -> int:
    a, b = _parse_version(current), _parse_version(latest)
    return (a > b) - (a < b)


def install_dir() -> str:
    """目前程式所在的安裝目錄(onedir 為 WAV2FLAC.exe 所在資料夾)。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class LatestRelease:
    version: str
    name: str
    html_url: str
    asset_url: str
    asset_name: str


def latest_release() -> LatestRelease:
    url = f"{GITHUB_API}/{REPO}/releases/latest"
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        data = json.load(r)
    tag = (data.get("tag_name") or data.get("name") or "").strip()
    ver = _parse_version(tag)
    asset_url, asset_name = "", ""
    for a in (data.get("assets") or []):
        n = a.get("name", "")
        u = a.get("browser_download_url", "") if a.get("browser_download_url") else ""
        if not u or not n.lower().endswith(".zip"):
            continue
        if not asset_url:
            asset_url, asset_name = u, n
        if _parse_version(n) == ver:
            asset_url, asset_name = u, n
            break
    return LatestRelease(tag, data.get("name", tag),
                         data.get("html_url", ""), asset_url, asset_name)


def _extract_zip(zip_path: str, dest: str) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for zi in zf.infolist():
            name = zi.filename
            if not (zi.flag_bits & 0x800):
                try:
                    name = name.encode("cp437").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    try:
                        name = name.encode("cp437").decode("big5")
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        pass
            target = os.path.join(dest, *name.split("/"))
            if zi.is_dir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(zi) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def _find_new_dir(extract_root: str) -> str:
    for dp, _dn, fn in os.walk(extract_root):
        if "WAV2FLAC.exe" in fn:
            return dp
    return extract_root


def _copy_tree(src: str, dst: str) -> None:
    for dp, _dn, fn in os.walk(src):
        rel = os.path.relpath(dp, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for f in fn:
            shutil.copy2(os.path.join(dp, f), os.path.join(target, f))


def _write_update_bat(new_dir: str, dest: str, tmp_dir: str, pid: int) -> str:
    bat = (
        "@echo off\r\n"
        ":wait\r\n"
        f"tasklist /FI \"PID eq {pid}\" | find \"{pid}\" >nul\r\n"
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        f'xcopy /E /Y /I /Q /R /W "{new_dir}\\*" "{dest}"\r\n'
        f'rmdir /S /Q "{tmp_dir}"\r\n'
        f'start "" "{dest}\\WAV2FLAC.exe"\r\n'
    )
    bat_path = os.path.join(tempfile.gettempdir(), "_wav2flac_update.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat)
    return bat_path


class UpdateWorker(QObject):
    checked = Signal(object)    # dict: has_update/latest_version/url/... 或 {"error": ...}
    progress = Signal(int)      # 下載百分比 0-100
    log = Signal(str)
    done = Signal(object)       # dict: ok/cancelled/message

    def __init__(self, current_version: str, parent=None) -> None:
        super().__init__(parent)
        self.current_version = current_version
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    # ------------------------------------------------- check
    def run_check(self) -> None:
        try:
            rel = latest_release()
            has_newer = compare_versions(self.current_version, rel.version) < 0
            self.checked.emit({
                "has_update": has_newer,
                "latest_version": rel.version,
                "current_version": self.current_version,
                "url": rel.asset_url,
                "asset_name": rel.asset_name,
                "page": rel.html_url,
            })
        except Exception as e:  # noqa: BLE001
            self.checked.emit({"error": str(e)})

    # ------------------------------------------------- update
    def run_update(self, url: str) -> None:
        tmp_dir = tempfile.mkdtemp(prefix="wav2flac_up_")
        try:
            self.log.emit("下載更新包...")
            fname = os.path.basename(url.split("?")[0]) or "update.zip"
            zip_path = os.path.join(tmp_dir, fname)
            self._download(url, zip_path)
            if self._cancel_event.is_set():
                self._cleanup(tmp_dir)
                self.done.emit({"ok": True, "cancelled": True})
                return

            self.log.emit("下載完成,解開中...")
            extract_root = os.path.join(tmp_dir, "extract")
            os.makedirs(extract_root, exist_ok=True)
            _extract_zip(zip_path, extract_root)
            new_dir = _find_new_dir(extract_root)
            dest = install_dir()

            if getattr(sys, "frozen", False):
                self.log.emit("即將重新啟動並覆蓋檔案...")
                bat = _write_update_bat(new_dir, dest, tmp_dir, os.getpid())
                flags = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
                subprocess.Popen(
                    bat, shell=True, close_fds=True, creationflags=flags,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.5)
                os._exit(0)
            else:
                self.log.emit("更新安裝中(開發模式)...")
                _copy_tree(new_dir, dest)
                self._cleanup(tmp_dir)
                self._cleanup_bat()
                self.log.emit("更新完成,請重新啟動程式。")
                self.done.emit({"ok": True})
        except InterruptedError:
            self._cleanup(tmp_dir)
            self.done.emit({"ok": True, "cancelled": True})
        except Exception as e:  # noqa: BLE001
            self._cleanup(tmp_dir)
            self.done.emit({"ok": False, "message": str(e)})

    def _download(self, url: str, dest: str) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as f:
                while True:
                    if self._cancel_event.is_set():
                        raise InterruptedError
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        self.progress.emit(int(done * 100 / total))

    @staticmethod
    def _cleanup(tmp_dir: str) -> None:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _cleanup_bat() -> None:
        bat = os.path.join(tempfile.gettempdir(), "_wav2flac_update.bat")
        try:
            if os.path.isfile(bat):
                os.remove(bat)
        except OSError:
            pass
