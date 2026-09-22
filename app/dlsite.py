from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .file_matcher import _norm_stem, MediaPair, PairStatus
from . import archive as _archive

# 音訊:僅 WAV(DL 商品以 WAV 為無損源)
AUDIO_EXTS = {".wav"}
# 副檔案:VTT 與 LRC(含 x.wav.vtt / x.wav.lrc 雙副名)
SUBTITLE_SUFFIXES = (".vtt", ".lrc")
# 可清除之低損格式(丟回收桶)
TRASHABLE_EXTS = {".mp3", ".aac", ".ogg", ".wma", ".opus"}

_cache_dirs: List[str] = []


def _is_subtitle(name: str) -> bool:
    n = name.lower()
    return any(n.endswith(s) for s in SUBTITLE_SUFFIXES)


@dataclass
class DlSiteScan:
    pairs: List[MediaPair] = field(default_factory=list)
    trashable: List[str] = field(default_factory=list)
    scanned_roots: List[str] = field(default_factory=list)
    extract_count: int = 0

    @property
    def matched(self) -> List[MediaPair]:
        return [p for p in self.pairs if p.status == PairStatus.MATCHED]


def _walk_dir(root: str, audio: List[str], subs: Dict[str, str],
              trash: List[str]) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        # 確定性排序
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in AUDIO_EXTS:
                audio.append(full)
            elif _is_subtitle(fn):
                stem = _norm_stem(os.path.splitext(fn)[0])
                subs.setdefault(stem, full)
            elif ext in TRASHABLE_EXTS:
                trash.append(full)


def _resolve_sources(inputs: List[str]) -> List[str]:
    """把輸入(資料夾/壓縮檔)展開為可掃描的目錄;壓縮檔先解開到暫存。"""
    roots: List[str] = []
    for raw in inputs:
        if not raw:
            continue
        path = os.path.normpath(raw)
        if _archive.is_archive(path) and os.path.isfile(path):
            tmp = tempfile.mkdtemp(prefix="wav2flac_dl_")
            try:
                _archive.extract_archive(path, tmp)
                roots.append(tmp)
                _cache_dirs.append(tmp)
            except Exception:
                continue
        elif os.path.isdir(path):
            roots.append(path)
        elif os.path.isfile(path) and os.path.splitext(path)[1].lower() in AUDIO_EXTS:
            roots.append(os.path.dirname(path))
    return roots


def scan_dlsite(inputs: List[str]) -> DlSiteScan:
    result = DlSiteScan()
    roots = _resolve_sources(inputs)
    result.scanned_roots = roots
    audio: List[str] = []
    subs: Dict[str, str] = {}
    trash: List[str] = []
    for r in roots:
        _walk_dir(r, audio, subs, trash)
    result.trashable = trash

    audio_by_stem: Dict[str, str] = {}
    for a in audio:
        stem = _norm_stem(os.path.splitext(os.path.basename(a))[0])
        audio_by_stem.setdefault(stem, a)

    all_stems = list(dict.fromkeys(list(audio_by_stem.keys()) + list(subs.keys())))
    for stem in all_stems:
        a = audio_by_stem.get(stem)
        s = subs.get(stem)
        if a and s:
            result.pairs.append(MediaPair(a, s, None, PairStatus.MATCHED))
        elif a:
            result.pairs.append(MediaPair(a, None, None, PairStatus.MISSING_SUBTITLE,
                                          "subtitle not found"))
        else:
            result.pairs.append(MediaPair(None, s, None, PairStatus.MISSING_AUDIO,
                                          "audio not found"))
    return result


def product_top(path: str) -> str:
    """DLsite: the product's top folder is the nearest ancestor dir whose name
    starts with 'RJ'; if none, fall back to the parent of the file."""
    path = os.path.normpath(path)
    d = os.path.dirname(path)
    while d and os.path.isdir(d):
        if os.path.basename(d).lower().startswith("rj"):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(path)


def cleanup_cache() -> None:
    import shutil
    for d in _cache_dirs:
        try:
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass
    _cache_dirs.clear()
