from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class PairStatus(Enum):
    MATCHED = "matched"
    MISSING_SUBTITLE = "missing_subtitle"
    MISSING_AUDIO = "missing_audio"
    SKIPPED = "skipped"


@dataclass
class MediaPair:
    audio_path: Optional[str]
    subtitle_path: Optional[str]
    output_dir: Optional[str] = None
    status: PairStatus = PairStatus.SKIPPED
    note: str = ""

    @property
    def stem(self) -> str:
        for p in (self.audio_path, self.subtitle_path):
            if p:
                return os.path.splitext(os.path.basename(p))[0]
        return ""

    @property
    def ready(self) -> bool:
        return self.status == PairStatus.MATCHED and bool(self.audio_path) and bool(self.subtitle_path)


AUDIO_EXTS = {".wav"}
SUBTITLE_EXTS = {".vtt"}


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _collect(paths: List[str], exts: set, target: Dict[str, str]) -> None:
    for p in paths:
        if not p:
            continue
        base = os.path.normpath(p)
        if os.path.isdir(base):
            try:
                entries = sorted(os.listdir(base))
            except OSError:
                continue
            for name in entries:
                full = os.path.join(base, name)
                if os.path.isfile(full) and _ext(full) in exts:
                    stem = os.path.splitext(name)[0]
                    target.setdefault(stem, full)
        elif os.path.isfile(base) and _ext(base) in exts:
            stem = os.path.splitext(os.path.basename(base))[0]
            target.setdefault(stem, base)


def scan_paths(audio_sources: List[str],
               subtitle_sources: List[str],
               output_dir: Optional[str]) -> List[MediaPair]:
    """Pair WAV files with VTT files by filename stem."""
    stem_audio: Dict[str, str] = {}
    stem_subs: Dict[str, str] = {}
    _collect(audio_sources, AUDIO_EXTS, stem_audio)
    _collect(subtitle_sources, SUBTITLE_EXTS, stem_subs)

    all_stems = list(dict.fromkeys(list(stem_audio.keys()) + list(stem_subs.keys())))
    pairs: List[MediaPair] = []
    for stem in all_stems:
        audio = stem_audio.get(stem)
        sub = stem_subs.get(stem)
        if audio and sub:
            pairs.append(MediaPair(audio, sub, output_dir, PairStatus.MATCHED))
        elif audio:
            pairs.append(MediaPair(audio, None, output_dir,
                                   PairStatus.MISSING_SUBTITLE, "subtitle not found"))
        else:
            pairs.append(MediaPair(None, sub, output_dir,
                                   PairStatus.MISSING_AUDIO, "audio not found"))
    return pairs
