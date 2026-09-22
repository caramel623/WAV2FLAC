from __future__ import annotations

import os
from typing import Dict, List, Optional

from mutagen.flac import FLAC
from mutagen.mp4 import MP4


def get_source_tags(audio_path: str) -> Dict[str, str]:
    """Read basic metadata (title/artist/album) from the source audio file."""
    tags: Dict[str, str] = {}
    try:
        audio = FLAC(audio_path)
        audio.tags.load()
        if audio.tags:
            for key in ("title", "artist", "album", "tracknumber", "albumartist"):
                val = audio.tags.get(key)
                if val:
                    tags[key] = str(val[0]).strip()
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
    track = source_tags.get("tracknumber", "")

    base: Dict[str, object] = {}
    if filename and not name:
        base["title"] = os.path.splitext(os.path.basename(filename))[0]
    if name:
        base["title"] = name
    if artist:
        base["artist"] = artist
    if album:
        base["album"] = album
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
        if meta.get("lyrics"):
            tags["\xa9lyr"] = [meta["lyrics"]]
        if meta.get("synced_lyrics"):
            tags["\xa9lyr"] = [meta["synced_lyrics"]]
            tags["\u0001LRC"] = [meta["synced_lyrics"]]
        audio.save()
        return True
    except Exception:
        return False


def apply_metadata(path: str, meta: Dict[str, object],
                   convert_to: str) -> bool:
    if convert_to == "m4a":
        return write_mp4(path, meta)
    return write_flac(path, meta)
