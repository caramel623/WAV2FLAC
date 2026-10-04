from __future__ import annotations

import os
from typing import Dict, List, Optional

from mutagen import File
from mutagen.flac import FLAC
from mutagen.mp4 import MP4


def _first(val) -> str:
    """mutagen tag 值可能是 str / list / 其他;統一取第一個字串。"""
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return str(val[0]).strip() if val else ""
    return str(val).strip()


def get_source_tags(audio_path: str) -> Dict[str, str]:
    """Read basic metadata (title/artist/album/track) from the **source** audio file.
    用 mutagen.File 自動偵測格式(WAV/FLAC/MP3/MP4...),避免用 FLAC class 開 MP4 時報錯。
    來源無 tag 時回傳 {},由 build_metadata_map 以檔名 fallback。"""
    tags: Dict[str, str] = {}
    try:
        audio = File(audio_path)
        if audio is not None and audio.tags:
            t = audio.tags
            for key in ("title", "artist", "album", "tracknumber", "albumartist"):
                v = _first(t.get(key))
                if v:
                    tags[key] = v
    except Exception:
        pass
    return tags


def build_metadata_map(source_tags: Dict[str, str],
                       lrc: Optional[str] = None,
                       unsynced: Optional[str] = None,
                       filename: str = "") -> Dict[str, object]:
    name = source_tags.get("title")
    artist = source_tags.get("artist")
    album = source_tags.get("album")
    albumartist = source_tags.get("albumartist")
    track = source_tags.get("tracknumber", "")

    base: Dict[str, object] = {}
    # 無來源 title 時以「檔名」當 title(保留檔名資訊),有則用來源
    if name:
        base["title"] = name
    elif filename:
        base["title"] = os.path.splitext(os.path.basename(filename))[0]
    if artist:
        base["artist"] = artist
    if album:
        base["album"] = album
    if albumartist:
        base["albumartist"] = albumartist
    if track:
        base["tracknumber"] = track
    if unsynced:
        base["lyrics"] = unsynced
    if lrc and lrc.strip():
        base["synced_lyrics"] = lrc
    return base


def write_flac(path: str, meta: Dict[str, object]) -> bool:
    try:
        audio = FLAC(path)
        if audio.tags is None:
            audio.add_tags()
        audio.tags["title"] = meta.get("title") or audio.tags.get("title") or [os.path.splitext(os.path.basename(path))[0]]
        if meta.get("artist"):
            audio.tags["artist"] = meta["artist"]
        if meta.get("album"):
            audio.tags["album"] = meta["album"]
        if meta.get("albumartist"):
            audio.tags["albumartist"] = meta["albumartist"]
        if meta.get("tracknumber"):
            audio.tags["tracknumber"] = meta["tracknumber"]
        if meta.get("lyrics"):
            audio.tags["unsyncedlyrics"] = [meta["lyrics"]]
        if meta.get("synced_lyrics"):
            audio.tags["syncedlyrics"] = [meta["synced_lyrics"]]
        audio.save()
        return True
    except Exception:
        return False


def write_mp4(path: str, meta: Dict[str, object]) -> bool:
    try:
        audio = MP4(path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        if meta.get("title"):
            tags["\xa9nam"] = [meta["title"]]
        if meta.get("artist"):
            tags["\xa9ART"] = [meta["artist"]]
        if meta.get("album"):
            tags["\xa9alb"] = [meta["album"]]
        if meta.get("albumartist"):
            tags["aART"] = [meta["albumartist"]]
        if meta.get("tracknumber"):
            # MP4 track 編號為 "n/總" 字串; 來源無總數時只放本號
            tags["\xa9trk"] = [str(meta["tracknumber"])]
        # M4A 歌詞: \xa9lyr 放 unsynced(純歌詞)、\u0001LRC 放 synced;
        # 無 unsynced 时才以 synced 墊 \xa9lyr, 避免純歌詞被 synced 覆寫丟失
        if meta.get("lyrics"):
            tags["\xa9lyr"] = [meta["lyrics"]]
        if meta.get("synced_lyrics"):
            tags["\u0001LRC"] = [meta["synced_lyrics"]]
            if not meta.get("lyrics"):
                tags["\xa9lyr"] = [meta["synced_lyrics"]]
        audio.save()
        return True
    except Exception:
        return False


def apply_metadata(path: str, meta: Dict[str, object],
                   convert_to: str) -> bool:
    if convert_to == "m4a":
        return write_mp4(path, meta)
    return write_flac(path, meta)
