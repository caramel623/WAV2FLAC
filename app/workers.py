from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal, QThread

from .audio_converter import convert_audio, verify_output
from .file_matcher import MediaPair
from .metadata_writer import apply_metadata, build_metadata_map, get_source_tags
from .subtitle_converter import cues_to_lrc, cues_to_unsynced, parse_subtitle


@dataclass
class ConversionConfig:
    convert_to: str = "flac"
    output_dir: str = ""
    overwrite_policy: str = "skip"
    aac_bitrate: str = "192k"
    flac_compression: int = 5
    target_sample_rate: str = "44100"
    embed_lyrics: bool = True
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    trash_map: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def ext(self) -> str:
        return "m4a" if self.convert_to == "m4a" else "flac"


@dataclass
class JobItem:
    pair: MediaPair
    index: int
    total: int


@dataclass
class ItemResult:
    audio: Optional[str]
    status: str
    output: str = ""
    message: str = ""


@dataclass
class BatchSummary:
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False


class BatchWorker(QObject):
    progress = Signal(int, int, str, float)  # done, total, current_stem, item_pct
    item_finished = Signal(object)       # ItemResult
    log = Signal(str)
    dlsite_mp3s = Signal(list)           # 可清除的 MP3(成功後)
    finished = Signal(object)            # BatchSummary

    def __init__(self, config: ConversionConfig,
                 jobs: List[JobItem], parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.jobs = jobs
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def _resolve_output(self, pair: MediaPair) -> tuple:
        out_dir = (pair.output_dir or self.config.output_dir
                   or os.path.dirname(pair.audio_path or pair.subtitle_path or ""))
        stem = pair.stem
        base = f"{stem}.{self.config.ext}"
        out_path = os.path.join(out_dir, base)
        if os.path.isfile(out_path):
            if self.config.overwrite_policy == "overwrite":
                return out_path, "overwrite"
            if self.config.overwrite_policy == "rename":
                out_path = _auto_rename(os.path.dirname(out_path), stem, self.config.ext)
                return out_path, "rename"
            return out_path, "skip"
        return out_path, "new"

    def run(self) -> None:
        summary = BatchSummary(total=len(self.jobs), cancelled=False)
        done = 0
        for job in self.jobs:
            if self._cancel.is_set():
                summary.cancelled = True
                self.progress.emit(done, summary.total, "cancelled", 100.0)
                continue
            pair = job.pair
            result = self._process_one(job)
            self.item_finished.emit(result)
            if result.status == "success":
                summary.success += 1
            elif result.status == "skipped":
                summary.skipped += 1
            else:
                summary.failed += 1
            done += 1
            self.progress.emit(done, summary.total, pair.stem, 100.0)
        self.finished.emit(summary)

    def _log(self, msg: str) -> None:
        safe = str(msg)
        self.log.emit(safe)

    def _process_one(self, job: JobItem) -> ItemResult:
        pair = job.pair
        if not pair.ready:
            return ItemResult(pair.audio_path, "skipped", message=(pair.note or "not matched"))

        out_path, action = self._resolve_output(pair)
        idx = job.index
        total = job.total
        self._log(f"[{idx}/{total}] {pair.stem}")

        if action == "skip":
            self._log(f"    略過(已存在):{os.path.basename(out_path)}")
            return ItemResult(pair.audio_path, "skipped", message="exists, policy=skip")

        out_dir = os.path.dirname(out_path)
        os.makedirs(out_dir, exist_ok=True)

        # 1) Convert audio (即時進度写入 LOG)
        tmp = out_path + ".tmp"
        self._log(f"    轉檔中 … {os.path.basename(pair.audio_path)} → {self.config.convert_to.upper()}")

        def _item_progress(pct: float) -> None:
            # 把當前項目的百分比映射到整體進度列
            self.progress.emit(job.index, job.total, pair.stem, pct)

        ok = convert_audio(
            self.config.ffmpeg_path, pair.audio_path, tmp,
            self.config.convert_to, self.config.aac_bitrate,
            self.config.flac_compression, self.config.target_sample_rate,
            ffprobe_path=self.config.ffprobe_path,
            log_callback=self._log,
            progress_callback=_item_progress,
            cancel_event=self._cancel,
        )
        if self._cancel.is_set():
            self._log(f"    已取消 {pair.stem}")
            return ItemResult(pair.audio_path, "cancelled", message="cancelled")
        if not ok:
            return ItemResult(pair.audio_path, "failed", message="ffmpeg error")

        # 2) Parse subtitle + write LRC
        lrc_text = ""
        unsynced_text = ""
        lrc_path = os.path.splitext(out_path)[0] + ".lrc"
        try:
            is_lrc_src = pair.subtitle_path.lower().endswith(".lrc")
            if is_lrc_src:
                # LRC 來源:直接複製(保留原標籤/順序),並解析 unsynced
                import shutil
                shutil.copyfile(pair.subtitle_path, lrc_path)
                with open(pair.subtitle_path, "rb") as f:
                    lrc_text = f.read().decode("utf-8", errors="replace")
                unsynced_text = "\n".join(
                    l.strip() for l in lrc_text.splitlines()
                    if l.strip() and not l.strip().startswith("[")
                )
                self._log("    已複製 LRC(來源)")
            else:
                self._log("    解析 VTT 字幕 …")
                cues = parse_subtitle(pair.subtitle_path)
                lrc_text = cues_to_lrc(cues)
                unsynced_text = cues_to_unsynced(cues)
                with open(lrc_path, "w", encoding="utf-8") as f:
                    f.write(lrc_text)
                self._log(f"    已產生 LRC({len(cues)} 段)")
        except Exception as e:  # noqa: BLE001
            self._log(f"    字幕處理失敗:{e}")
            return ItemResult(pair.audio_path, "failed", message=f"subtitle error: {e}")

        # 3) Metadata
        if self.config.embed_lyrics:
            self._log("    寫入金標與歌詞 …")
            source_tags = get_source_tags(tmp)
            meta = build_metadata_map(source_tags, lrc=lrc_text,
                                      unsynced=unsynced_text,
                                      filename=pair.audio_path)
            apply_metadata(tmp, meta, self.config.convert_to)

        # 4) Verify + rename tmp -> final
        if not verify_output(tmp, self.config.ffprobe_path):
            if os.path.isfile(tmp):
                os.remove(tmp)
            self._log(f"    驗證失敗(輸出無效){pair.stem}")
            return ItemResult(pair.audio_path, "failed", message="output invalid")
        os.replace(tmp, out_path)
        self._log(f"    ✔ 完成 → {os.path.basename(out_path)}")
        mp3s = self.config.trash_map.get(os.path.basename(pair.audio_path), [])
        if mp3s:
            self.dlsite_mp3s.emit(mp3s)
        return ItemResult(pair.audio_path, "success", output=out_path)


def _auto_rename(dirname: str, stem: str, ext: str) -> str:
    base = os.path.join(dirname, stem)
    i = 1
    while os.path.isfile(f"{base} ({i}).{ext}"):
        i += 1
    return f"{base} ({i}).{ext}"
