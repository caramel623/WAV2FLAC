from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")
_SPEED_RE = re.compile(r"speed=([0-9.]+)x")


def _parse_time_s(line: str) -> Optional[float]:
    m = _TIME_RE.search(line)
    if not m:
        return None
    h, mi, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 100.0


def _fmt_mmss(total_s: float) -> str:
    total_s = max(0, int(total_s))
    m, s = divmod(total_s, 60)
    return f"{m:02d}:{s:02d}"


@dataclass
class AudioInfo:
    path: str
    duration_ms: int
    sample_rate: int
    channels: int
    codec: str


def probe_audio(ffprobe_path: str, path: str) -> Optional[AudioInfo]:
    cmd = [
        ffprobe_path, "-v", "error",
        "-show_format", "-show_streams",
        "-of", "json", path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True,
                              encoding="utf-8", errors="replace",
                              shell=False, timeout=30)
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None

    duration_ms = 0
    fmt = data.get("format", {})
    try:
        duration_ms = int(float(fmt.get("duration", "0")) * 1000)
    except (ValueError, TypeError):
        duration_ms = 0

    sample_rate = 0
    channels = 0
    codec = ""
    for st in data.get("streams", []):
        if st.get("codec_type") == "audio":
            sample_rate = int(st.get("sample_rate") or 0)
            channels = int(st.get("channels") or 0)
            codec = st.get("codec_name") or ""
            break
    return AudioInfo(path, duration_ms, sample_rate, channels, codec)


def _build_ffmpeg_args(src: str, dst: str, convert_to: str,
                       aac_bitrate: str, flac_compression: int,
                       target_sample_rate: str) -> list:
    if convert_to == "m4a":
        sr = target_sample_rate if target_sample_rate else "44100"
        return [
            "-y", "-i", src,
            "-vn", "-c:a", "aac", "-b:a", aac_bitrate,
            "-ar", sr, "-movflags", "+faststart", "-f", "mp4", dst,
        ]
    # flac (lossless)
    return [
        "-y", "-i", src,
        "-vn", "-c:a", "flac", "-compression_level", str(flac_compression),
        "-f", "flac", dst,
    ]


def convert_audio(ffmpeg_path: str, src: str, dst: str, convert_to: str,
                  aac_bitrate: str = "192k", flac_compression: int = 5,
                  target_sample_rate: str = "44100",
                  ffprobe_path: str = "",
                  progress_callback=None,
                  log_callback: Optional[Callable[[str], None]] = None,
                  cancel_event: Optional[threading.Event] = None) -> bool:
    args = _build_ffmpeg_args(src, dst, convert_to, aac_bitrate,
                              flac_compression, target_sample_rate)
    cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "info",
           "-stats_period", "0.1", "-nostdin"] + args

    def _log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    def _progress(pct: float) -> None:
        if progress_callback:
            progress_callback(pct)

    # 取得來源長度以計算百分比
    duration_s = 0.0
    if ffprobe_path:
        info = probe_audio(ffprobe_path, src)
        if info:
            duration_s = info.duration_ms / 1000.0

    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, shell=False,
    )

    last_pct = -1.0
    last_speed = 1.0
    last_eta_logged = -1.0
    start_wall = time.monotonic()
    err_lines: List[str] = []

    try:
        assert proc.stderr is not None
        for raw in proc.stderr:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if "frame=" in line or "time=" in line:
                t = _parse_time_s(line)
                sm = _SPEED_RE.search(line)
                if sm:
                    last_speed = max(0.01, float(sm.group(1)))
                if t is None or not duration_s:
                    continue
                pct = min(100.0, t / duration_s * 100.0)
                if pct > last_pct:
                    last_pct = pct
                    _progress(pct)
                    # 約每 2 秒更新一次 LOG,避免刷屏
                    elapsed = time.monotonic() - start_wall
                    if last_eta_logged < 0 or elapsed - last_eta_logged >= 2.0:
                        eta_s = (duration_s - t) / last_speed if last_speed else -1
                        eta_txt = _fmt_mmss(eta_s) if eta_s >= 0 else "--:--"
                        cur_s, tot_s = _fmt_mmss(t), _fmt_mmss(duration_s)
                        _log(f"    轉換中 {cur_s}/{tot_s} ({last_pct:.0f}%) "
                             f"速度 {last_speed:.1f}x 預估剩餘 {eta_txt}")
                        last_eta_logged = elapsed
                continue
            if "error" in line.lower():
                err_lines.append(line)
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
    except Exception as e:  # noqa: BLE001
        _log(f"    FFmpeg 異常:{e}")
        return False

    if cancel_event is not None and cancel_event.is_set():
        return False
    if proc.returncode != 0:
        tail = " | ".join(err_lines[-3:]) or "(無詳細錯誤)"
        _log(f"    FFmpeg 失敗 (code {proc.returncode}):{tail}")
        return False
    if duration_s:
        _log(f"    轉檔完成 {duration_s:.1f}s → {convert_to.upper()}")
    return os.path.isfile(dst)


def verify_output(dst: str, ffprobe_path: str,
                  min_duration_ms: int = 100) -> bool:
    info = probe_audio(ffprobe_path, dst)
    if info is None:
        return False
    return info.duration_ms >= min_duration_ms
