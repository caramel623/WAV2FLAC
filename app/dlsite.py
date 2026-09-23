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
_archive_origins: Dict[str, str] = {}


def _is_subtitle(name: str) -> bool:
    n = name.lower()
    return any(n.endswith(s) for s in SUBTITLE_SUFFIXES)


@dataclass
class DlSiteScan:
    pairs: List[MediaPair] = field(default_factory=list)
    trashable: List[str] = field(default_factory=list)
    scanned_roots: List[str] = field(default_factory=list)
    extract_count: int = 0
    # temp_root(暫存解開目錄) -> 原始壓縮檔路徑
    archive_origins: Dict[str, str] = field(default_factory=dict)

    @property
    def matched(self) -> List[MediaPair]:
        return [p for p in self.pairs if p.status == PairStatus.MATCHED]


def _walk_dir(root: str, audio: List[str], subs: List[str],
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
                subs.append(full)
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
                _archive_origins[tmp] = path
            except Exception:
                continue
        elif os.path.isdir(path):
            roots.append(path)
        elif os.path.isfile(path) and os.path.splitext(path)[1].lower() in AUDIO_EXTS:
            roots.append(os.path.dirname(path))
    return roots


def _product_boundary(file_path: str, root: str) -> str:
    """選定 root 內的「商品邊界」:從檔案往上、最接近的 RJ 開頭資料夾(含 root 自身);
    若到 root 為止都沒 RJ,則以 root 本身為邊界。
    用途:把同一個 root 下的多個商品分開配對,避免跨商品(隔壁資料夾)串味。"""
    root = os.path.normpath(root)
    d = os.path.dirname(os.path.normpath(file_path))
    while True:
        if os.path.basename(d).lower().startswith("rj"):
            return d
        if d == root:
            return root
        parent = os.path.dirname(d)
        if parent == d:
            return root
        d = parent


def scan_dlsite(inputs: List[str]) -> DlSiteScan:
    result = DlSiteScan()
    _archive_origins.clear()
    roots = _resolve_sources(inputs)
    result.scanned_roots = roots

    for r in roots:
        audio: List[str] = []
        subs: List[str] = []
        trash: List[str] = []
        _walk_dir(r, audio, subs, trash)
        result.trashable.extend(trash)
        if r in _archive_origins:
            result.archive_origins[r] = _archive_origins[r]

        # 依「商品邊界 + stem」配對,避免同一 root 下多個商品(隔壁資料夾)互相干擾
        prod_audio: Dict[tuple, str] = {}
        for a in audio:
            b = _product_boundary(a, r)
            stem = _norm_stem(os.path.splitext(os.path.basename(a))[0])
            prod_audio.setdefault((b, stem), a)
        prod_subs: Dict[tuple, str] = {}
        for s in subs:
            b = _product_boundary(s, r)
            stem = _norm_stem(os.path.splitext(os.path.basename(s))[0])
            prod_subs.setdefault((b, stem), s)

        for key in list(dict.fromkeys(list(prod_audio.keys()) + list(prod_subs.keys()))):
            a = prod_audio.get(key)
            s = prod_subs.get(key)
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
