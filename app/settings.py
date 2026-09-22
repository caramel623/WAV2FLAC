from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

DEFAULT_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "settings.json")


@dataclass
class Settings:
    # FFmpeg
    ffmpeg_path: str = ""
    # Audio
    aac_bitrate: str = "192k"
    flac_compression: int = 5
    convert_to: str = "flac"  # "flac" | "m4a"
    target_sample_rate: str = "48000"  # for m4a only
    embed_lyrics: bool = True
    # Files
    source_audio: str = ""
    source_subtitle: str = ""
    output_dir: str = ""
    # Overwrite policy: "skip" | "overwrite" | "rename"
    overwrite_policy: str = "skip"
    # Logging
    log_dir: str = ""

    @staticmethod
    def load(path: str = DEFAULT_SETTINGS_PATH) -> "Settings":
        if not os.path.exists(path):
            return Settings()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            known = {f.name for f in Settings.__dataclass_fields__.values()}  # type: ignore[attr-defined]
            fields = [k for k in data.keys() if k in known]
            return Settings(**{k: data[k] for k in fields})
        except (json.JSONDecodeError, TypeError, ValueError, OSError):
            return Settings()

    def save(self, path: str = DEFAULT_SETTINGS_PATH) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except OSError:
            pass
