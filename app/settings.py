from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

DEFAULT_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "settings.json")

# 型別字串(因 from __future__ import annotations, f.type 常為字串)對應實際型別
_TYPE_ALIASES = {"str": str, "int": int, "bool": bool}


def _matches_type(val, typ) -> bool:
    """檢查值是否符合欄位宣告的型別;不符時欄位回退預設值。
    bool 特別處理: bool 不是 int 的子類, 但 int 不該通過 bool 欄位;
    反之 int 值通過 bool 欄位會失真, 故严格要求。"""
    if isinstance(typ, str):
        typ = _TYPE_ALIASES.get(typ, typ)
    if not isinstance(typ, type):
        return True  # 未知/無型別: 放行
    if typ is bool:
        return isinstance(val, bool)
    # int 欄位允許 int(排除 bool, 因 bool 是 int 子型別)
    if typ is int:
        return isinstance(val, int) and not isinstance(val, bool)
    if typ is str:
        return isinstance(val, str)
    return isinstance(val, typ)


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
    # 模式: "manual" | "dlsite"
    mode: str = "manual"
    # DLsite 模式輸入(最上層資料夾/壓縮檔,可多個;以 ; 分隔)
    dlsite_input: str = ""
    # DL 模式自動清除 MP3 等低損檔(丟回收桶)
    trash_mp3: bool = False
    # DL 模式輸出子資料夾名稱(留空 = 使用格式名 FLAC/M4A)
    dlsite_output_sub: str = ""
    # DL 模式輸出時保留原始資料夾結構(遞迴):FLAC/WAV_NoSE/01.flac
    mirror_structure: bool = False

    @staticmethod
    def load(path: str = DEFAULT_SETTINGS_PATH) -> "Settings":
        if not os.path.exists(path):
            return Settings()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return Settings()
            defaults = Settings()
            valid: "dict[str, object]" = {}
            for f in Settings.__dataclass_fields__.values():  # type: ignore[attr-defined]
                key = f.name
                if key not in data:
                    continue
                val = data[key]
                typ = f.type  # 可能為 str(文字化型別)或實際型別
                if not _matches_type(val, typ):
                    # 型別不符(如 bool 被存成字串 "true" 或 aac_bitrate 是 int):回退預設值
                    val = getattr(defaults, key)
                valid[key] = val
            return Settings(**valid)
        except (json.JSONDecodeError, TypeError, ValueError, OSError):
            return Settings()

    def save(self, path: str = DEFAULT_SETTINGS_PATH) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except OSError:
            pass
