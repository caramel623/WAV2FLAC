from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional


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
        proc = subprocess.run(cmd, capture_output=True, text=True,
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
                  progress_callback=None,
                  cancel_event: Optional[threading.Event] = None) -> bool:
    args = _build_ffmpeg_args(src, dst, convert_to, aac_bitrate,
                              flac_compression, target_sample_rate)
    cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error"] + args
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, shell=False)
    try:
        _, err = proc.communicate(timeout=3600)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return cancel_event is not None and cancel_event.is_set()
    if cancel_event is not None and cancel_event.is_set():
        return False
    if proc.returncode != 0:
        return False
    return os.path.isfile(dst)


def verify_output(dst: str, ffprobe_path: str,
                  min_duration_ms: int = 100) -> bool:
    info = probe_audio(ffprobe_path, dst)
    if info is None:
        return False
    return info.duration_ms >= min_duration_ms
