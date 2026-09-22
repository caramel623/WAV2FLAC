from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class FFmpegInfo:
    found: bool
    ffmpeg_path: str
    ffprobe_path: str
    version: str
    source: str

    @property
    def ready(self) -> bool:
        return self.found and bool(self.ffmpeg_path) and bool(self.ffprobe_path)


def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _subdirs(path: str) -> List[str]:
    out: List[str] = []
    try:
        for name in os.listdir(path):
            p = os.path.join(path, name)
            if os.path.isdir(p):
                out.append(p)
    except OSError:
        pass
    return out


def _candidate_dirs() -> List[str]:
    dirs: List[str] = []
    app = _app_dir()
    # 1) The app's own folder (allows shipping ffmpeg.exe next to the exe) and its bin subfolder
    dirs.append(app)
    dirs.append(os.path.join(app, "bin"))
    for base in (app, os.path.dirname(app)):
        for rel in ("ffmpeg/bin", "tools/ffmpeg/bin"):
            dirs.append(os.path.join(base, rel))
    dirs.append(r"C:\ffmpeg\bin")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    dirs.append(os.path.join(pf, "ffmpeg", "bin"))
    # WinGet package layout (e.g. Gyan.FFmpeg_...)
    winget = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Microsoft", "WinGet", "Packages",
    )
    if os.path.isdir(winget):
        try:
            for entry in os.listdir(winget):
                if "ffmpeg" in entry.lower():
                    full = os.path.join(winget, entry)
                    if os.path.isdir(full):
                        for sub in _subdirs(full):
                            cand = os.path.join(sub, "bin")
                            if cand not in dirs:
                                dirs.append(cand)
                        direct = os.path.join(full, "bin")
                        if direct not in dirs:
                            dirs.append(direct)
        except OSError:
            pass
    return dirs


def _find_in_dirs(name: str, dirs: List[str]) -> Optional[str]:
    exe = name if name.lower().endswith(".exe") else name + ".exe"
    for d in dirs:
        candidate = os.path.join(d, exe)
        if os.path.isfile(candidate):
            return candidate
    return None


def find_ffmpeg() -> Optional[str]:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    return _find_in_dirs("ffmpeg", _candidate_dirs())


def find_ffprobe() -> Optional[str]:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    return _find_in_dirs("ffprobe", _candidate_dirs())


def get_ffmpeg_version(ffmpeg_path: str) -> str:
    try:
        proc = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True, encoding="utf-8", errors="replace",
            shell=False, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def get_ffmpeg_info(preferred_ffmpeg: str = "",
                    preferred_ffprobe: str = "") -> FFmpegInfo:
    ffmpeg: Optional[str] = None
    probe: Optional[str] = None
    source = "none"

    if preferred_ffmpeg and os.path.isfile(preferred_ffmpeg):
        ffmpeg = preferred_ffmpeg
        source = "manual"
    if not ffmpeg:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            source = "PATH"
    if not ffmpeg:
        ffmpeg = _find_in_dirs("ffmpeg", _candidate_dirs())
        if ffmpeg:
            source = "auto"

    if preferred_ffprobe and os.path.isfile(preferred_ffprobe):
        probe = preferred_ffprobe
    elif ffmpeg and source == "manual":
        # 手動指定 ffmpeg 時,優先採用同資料夾的 ffprobe.exe
        same_dir = os.path.dirname(ffmpeg)
        cand = os.path.join(same_dir, "ffprobe.exe")
        if not os.path.isfile(cand):
            cand = os.path.join(same_dir, "FFprobe.exe")
        if os.path.isfile(cand):
            probe = cand
    if not probe:
        probe = shutil.which("ffprobe")
    if not probe:
        probe = _find_in_dirs("ffprobe", _candidate_dirs())

    version = get_ffmpeg_version(ffmpeg or "") if ffmpeg else ""
    return FFmpegInfo(
        found=bool(ffmpeg and probe),
        ffmpeg_path=ffmpeg or "",
        ffprobe_path=probe or "",
        version=version,
        source=source,
    )
