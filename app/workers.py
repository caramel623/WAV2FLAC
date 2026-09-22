from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import List, Optional

from PySide6.QtCore import QObject, Signal, QThread

from .audio_converter import convert_audio, verify_output
from .file_matcher import MediaPair
from .metadata_writer import apply_metadata, build_metadata_map, get_source_tags
from .subtitle_converter import cues_to_lrc, cues_to_unsynced, parse_vtt


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
    progress = Signal(int, int, str)     # done, total, current_stem
    item_finished = Signal(object)       # ItemResult
    log = Signal(str)
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
        out_dir = self.config.output_dir or os.path.dirname(pair.audio_path or pair.subtitle_path or "")
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
                self.progress.emit(done + 1, summary.total, "cancelled")
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
            self.progress.emit(done, summary.total, pair.stem)
        self.finished.emit(summary)

    def _process_one(self, job: JobItem) -> ItemResult:
        pair = job.pair
        if not pair.ready:
            return ItemResult(pair.audio_path, "skipped", message=(pair.note or "not matched"))

        out_path, action = self._resolve_output(pair)
        if action == "skip":
            return ItemResult(pair.audio_path, "skipped", message="exists, policy=skip")

        out_dir = os.path.dirname(out_path)
        os.makedirs(out_dir, exist_ok=True)

        # 1) Convert audio
        tmp = out_path + ".tmp"
        ok = convert_audio(
            self.config.ffmpeg_path, pair.audio_path, tmp,
            self.config.convert_to, self.config.aac_bitrate,
            self.config.flac_compression, self.config.target_sample_rate,
            cancel_event=self._cancel,
        )
        if self._cancel.is_set():
            return ItemResult(pair.audio_path, "cancelled", message="cancelled")
        if not ok:
            return ItemResult(pair.audio_path, "failed", message="ffmpeg error")

        # 2) Parse VTT + write LRC
        lrc_text = ""
        unsynced_text = ""
        try:
            cues = parse_vtt(pair.subtitle_path)
            lrc_text = cues_to_lrc(cues)
            unsynced_text = cues_to_unsynced(cues)
            lrc_path = os.path.splitext(out_path)[0] + ".lrc"
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write(lrc_text)
        except Exception as e:  # noqa: BLE001
            return ItemResult(pair.audio_path, "failed", message=f"vtt error: {e}")

        # 3) Metadata
        if self.config.embed_lyrics:
            source_tags = get_source_tags(tmp)
            meta = build_metadata_map(source_tags, lrc=lrc_text,
                                      unsynced=unsynced_text,
                                      filename=pair.audio_path)
            apply_metadata(tmp, meta, self.config.convert_to)

        # 4) Verify + rename tmp -> final
        if not verify_output(tmp, self.config.ffprobe_path):
            if os.path.isfile(tmp):
                os.remove(tmp)
            return ItemResult(pair.audio_path, "failed", message="output invalid")
        os.replace(tmp, out_path)
        self.log.emit(f"done: {pair.stem} -> {os.path.basename(out_path)}")
        return ItemResult(pair.audio_path, "success", output=out_path)


def _auto_rename(dirname: str, stem: str, ext: str) -> str:
    base = os.path.join(dirname, stem)
    i = 1
    while os.path.isfile(f"{base} ({i}).{ext}"):
        i += 1
    return f"{base} ({i}).{ext}"
