from __future__ import annotations

import os
from typing import List

from PySide6.QtCore import Qt, QSize, QThread
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QComboBox,
    QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QCheckBox, QWidget, QAbstractItemView, QSizePolicy,
)

from . import __version__
from .file_matcher import MediaPair, PairStatus, scan_paths
from .ffmpeg_manager import get_ffmpeg_info
from .settings import Settings
from .workers import BatchWorker, ConversionConfig, JobItem

_STATUS_TEXT = {
    PairStatus.MATCHED: "OK",
    PairStatus.MISSING_SUBTITLE: "no subtitle",
    PairStatus.MISSING_AUDIO: "no audio",
    PairStatus.SKIPPED: "skipped",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.pairs: List[MediaPair] = []
        self.worker: BatchWorker | None = None
        self.thread = None
        self.setWindowTitle(f"WAV2FLAC v{__version__}")
        self.resize(1000, 680)
        self.setAcceptDrops(True)
        self._build_ui()
        self._refresh_ffmpeg()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        root = QGridLayout()
        central.setLayout(root)
        self.setCentralWidget(central)

        root.addWidget(self._build_source_group(), 0, 0)
        root.addWidget(self._build_settings_group(), 0, 1)
        root.addWidget(self._build_table(), 1, 0, 1, 2)
        root.addWidget(self._build_progress_area(), 2, 0, 1, 2)
        root.addWidget(self._build_log_area(), 3, 0, 1, 2)
        root.setColumnStretch(0, 1)
        root.setColumnStretch(1, 1)
        root.setRowStretch(1, 1)

        self.statusBar().showMessage("Ready")

    def _build_source_group(self) -> QGroupBox:
        box = QGroupBox("Source")
        form = QFormLayout(box)

        self.audio_edit = QLineEdit(self.settings.source_audio)
        self.audio_edit.setReadOnly(True)
        b_audio = QPushButton("Add audio...")
        b_audio.clicked.connect(self._choose_audio)
        row_a = QHBoxLayout()
        row_a.addWidget(self.audio_edit, 1)
        row_a.addWidget(b_audio)
        form.addRow("Audio (WAV dir/files)", row_a)

        self.sub_edit = QLineEdit(self.settings.source_subtitle)
        self.sub_edit.setReadOnly(True)
        b_sub = QPushButton("Add subtitle...")
        b_sub.clicked.connect(self._choose_subtitle)
        row_s = QHBoxLayout()
        row_s.addWidget(self.sub_edit, 1)
        row_s.addWidget(b_sub)
        form.addRow("Subtitle (VTT dir/files)", row_s)

        self.out_edit = QLineEdit(self.settings.output_dir)
        b_out = QPushButton("Choose...")
        b_out.clicked.connect(self._choose_output)
        row_o = QHBoxLayout()
        row_o.addWidget(self.out_edit, 1)
        row_o.addWidget(b_out)
        form.addRow("Output dir", row_o)

        self.scan_btn = QPushButton("Scan & Pair")
        self.scan_btn.clicked.connect(self._scan)
        form.addRow(self.scan_btn)
        return box

    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("Conversion")
        form = QFormLayout(box)

        self.convert_combo = QComboBox()
        self.convert_combo.addItem("FLAC (lossless)", "flac")
        self.convert_combo.addItem("M4A / AAC (lossy)", "m4a")
        idx = 1 if self.settings.convert_to == "m4a" else 0
        self.convert_combo.setCurrentIndex(idx)
        form.addRow("Target", self.convert_combo)

        self.aac_bitrate = QComboBox()
        for v in ("128k", "160k", "192k", "256k", "320k"):
            self.aac_bitrate.addItem(v)
        self.aac_bitrate.setCurrentText(self.settings.aac_bitrate)
        form.addRow("AAC bitrate", self.aac_bitrate)

        self.flac_comp = QSpinBox()
        self.flac_comp.setRange(0, 12)
        self.flac_comp.setValue(self.settings.flac_compression)
        form.addRow("FLAC level", self.flac_comp)

        self.sr_combo = QComboBox()
        for v in ("44100", "48000", "88200", "96000"):
            self.sr_combo.addItem(v)
        self.sr_combo.setCurrentText(self.settings.target_sample_rate)
        form.addRow("Sample rate (M4A)", self.sr_combo)

        self.policy_combo = QComboBox()
        self.policy_combo.addItem("Skip existing", "skip")
        self.policy_combo.addItem("Overwrite", "overwrite")
        self.policy_combo.addItem("Auto-rename", "rename")
        p = {"skip": 0, "overwrite": 1, "rename": 2}.get(self.settings.overwrite_policy, 0)
        self.policy_combo.setCurrentIndex(p)
        form.addRow("On conflict", self.policy_combo)

        self.embed_check = QCheckBox("Embed lyrics (LRC)")
        self.embed_check.setChecked(self.settings.embed_lyrics)
        form.addRow(self.embed_check)
        return box

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Stem", "Status", "Audio", "Subtitle"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        return self.table

    def _build_progress_area(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        lay.addWidget(self.start_btn)
        lay.addWidget(self.cancel_btn)
        lay.addWidget(self.progress, 1)
        lay.addWidget(QLabel(""))
        return w

    def _build_log_area(self) -> QGroupBox:
        box = QGroupBox("Log")
        lay = QGridLayout(box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(140)
        self.ffmpeg_label = QLabel("")
        self.ffmpeg_btn = QPushButton("Browse...")
        self.ffmpeg_btn.clicked.connect(self._choose_ffmpeg)
        top = QHBoxLayout()
        top.addWidget(self.ffmpeg_label, 1)
        top.addWidget(self.ffmpeg_btn)
        lay.addLayout(top, 0, 0)
        lay.addWidget(self.log_view, 1, 0)
        return box

    # ------------------------------------------------------------- state
    def _refresh_ffmpeg(self) -> None:
        info = get_ffmpeg_info(self.settings.ffmpeg_path)
        if info.ready:
            self.ffmpeg_label.setText(f"FFmpeg found [{info.source}]: {info.version or 'version n/a'}")
            self.ffmpeg_label.setStyleSheet("color: green;")
        else:
            self.ffmpeg_label.setText("FFmpeg not found. Click Browse... to locate ffmpeg.exe")
            self.ffmpeg_label.setStyleSheet("color: red;")

    def _save_settings(self) -> None:
        self.settings.source_audio = self.audio_edit.text()
        self.settings.source_subtitle = self.sub_edit.text()
        self.settings.output_dir = self.out_edit.text()
        self.settings.convert_to = self.convert_combo.currentData()
        self.settings.aac_bitrate = self.aac_bitrate.currentText()
        self.settings.flac_compression = self.flac_comp.value()
        self.settings.target_sample_rate = self.sr_combo.currentText()
        self.settings.overwrite_policy = self.policy_combo.currentData()
        self.settings.embed_lyrics = self.embed_check.isChecked()
        self.settings.save()

    # ----------------------------------------------------------- slots
    def _choose_audio(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select audio folder", self.audio_edit.text())
        if d:
            self.audio_edit.setText(d)

    def _choose_subtitle(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select subtitle folder", self.sub_edit.text())
        if d:
            self.sub_edit.setText(d)

    def _choose_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select output folder", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def _choose_ffmpeg(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Select ffmpeg.exe", "", "ffmpeg (ffmpeg.exe)")
        if f:
            self.settings.ffmpeg_path = f
            self.settings.save()
            self._refresh_ffmpeg()

    def _scan(self) -> None:
        audio_src = [s for s in self.audio_edit.text().split(os.pathsep) if s]
        sub_src = [s for s in self.sub_edit.text().split(os.pathsep) if s]
        out = self.out_edit.text()
        self.pairs = scan_paths(audio_src, sub_src, out)
        self._populate_table()
        matched = sum(1 for p in self.pairs if p.status == PairStatus.MATCHED)
        self.statusBar().showMessage(f"Scanned: {len(self.pairs)} stems, {matched} matched")

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        for p in self.pairs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(p.stem))
            self.table.setItem(row, 1, QTableWidgetItem(_STATUS_TEXT.get(p.status, "")))
            self.table.setItem(row, 2, QTableWidgetItem(p.audio_path or ""))
            self.table.setItem(row, 3, QTableWidgetItem(p.subtitle_path or ""))

    def _start(self) -> None:
        self._save_settings()
        if not self.pairs:
            QMessageBox.warning(self, "WAV2FLAC", "No pairs. Click Scan & Pair first.")
            return
        matched = [p for p in self.pairs if p.status == PairStatus.MATCHED]
        if not matched:
            QMessageBox.warning(self, "WAV2FLAC", "No matched audio+subtitle pairs.")
            return
        info = get_ffmpeg_info(self.settings.ffmpeg_path)
        if not info.ready:
            QMessageBox.critical(self, "WAV2FLAC", "FFmpeg not found. Set it in the log area.")
            return
        if not self.out_edit.text():
            QMessageBox.warning(self, "WAV2FLAC", "Choose an output directory.")
            return

        jobs = [JobItem(pair=p, index=i, total=len(matched)) for i, p in enumerate(matched)]
        cfg = ConversionConfig(
            convert_to=self.convert_combo.currentData(),
            output_dir=self.out_edit.text(),
            overwrite_policy=self.policy_combo.currentData(),
            aac_bitrate=self.aac_bitrate.currentText(),
            flac_compression=self.flac_comp.value(),
            target_sample_rate=self.sr_combo.currentText(),
            embed_lyrics=self.embed_check.isChecked(),
            ffmpeg_path=info.ffmpeg_path,
            ffprobe_path=info.ffprobe_path,
        )
        self.worker = BatchWorker(cfg, jobs)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_finished.connect(self._on_item)
        self.worker.log.connect(self._append_log)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setRange(0, 0)
        self.progress.setFormat("Processing...")

    def _cancel(self) -> None:
        if self.worker:
            self.worker.request_cancel()
            self.statusBar().showMessage("Cancelling...")

    def _on_progress(self, done: int, total: int, stem: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total} - {stem}")

    def _on_item(self, result) -> None:
        self._append_log(f"[{result.status}] {os.path.basename(result.audio or '')} {result.message}")

    def _on_finished(self, summary) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait(30000)
            self.thread = None
            self.worker.deleteLater()
            self.worker = None
        self.progress.setFormat(f"Done: {summary.success} ok, {summary.failed} failed, "
                               f"{summary.skipped} skipped" + (", cancelled" if summary.cancelled else ""))
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.statusBar().showMessage(self.progress.format())

    def _append_log(self, text: str) -> None:
        self.log_view.append(text)

    # --------------------------------------------------------- drag drop
    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        audio: List[str] = []
        subs: List[str] = []
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.endswith(".vtt"):
                subs.append(path)
            elif path.endswith(".wav"):
                audio.append(path)
            elif os.path.isdir(path):
                audio.append(path)
                subs.append(path)
        if audio:
            base = self.audio_edit.text()
            self.audio_edit.setText((base + os.pathsep + os.pathsep.join(audio)).strip(os.pathsep))
        if subs:
            base = self.sub_edit.text()
            self.sub_edit.setText((base + os.pathsep + os.pathsep.join(subs)).strip(os.pathsep))
        self._scan()
