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
    PairStatus.MATCHED: "已配對",
    PairStatus.MISSING_SUBTITLE: "缺少字幕",
    PairStatus.MISSING_AUDIO: "缺少音訊",
    PairStatus.SKIPPED: "略過",
}

FFMPEG_DL_URL = "https://www.gyan.dev/ffmpeg/builds/"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.pairs: List[MediaPair] = []
        self.worker: BatchWorker | None = None
        self.thread = None
        self.setWindowTitle(f"WAV2FLAC 批次轉檔工具 v{__version__}")
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

        self.statusBar().showMessage("就緒")

    def _build_source_group(self) -> QGroupBox:
        box = QGroupBox("來源")
        form = QFormLayout(box)

        self.audio_edit = QLineEdit(self.settings.source_audio)
        self.audio_edit.setReadOnly(True)
        b_audio = QPushButton("新增...")
        b_audio.clicked.connect(self._choose_audio)
        row_a = QHBoxLayout()
        row_a.addWidget(self.audio_edit, 1)
        row_a.addWidget(b_audio)
        form.addRow("音訊 (WAV 資料夾或檔案)", row_a)

        self.sub_edit = QLineEdit(self.settings.source_subtitle)
        self.sub_edit.setReadOnly(True)
        b_sub = QPushButton("新增...")
        b_sub.clicked.connect(self._choose_subtitle)
        row_s = QHBoxLayout()
        row_s.addWidget(self.sub_edit, 1)
        row_s.addWidget(b_sub)
        form.addRow("字幕 (VTT 資料夾或檔案)", row_s)

        self.out_edit = QLineEdit(self.settings.output_dir)
        b_out = QPushButton("選取...")
        b_out.clicked.connect(self._choose_output)
        row_o = QHBoxLayout()
        row_o.addWidget(self.out_edit, 1)
        row_o.addWidget(b_out)
        form.addRow("輸出資料夾", row_o)

        self.scan_btn = QPushButton("掃描並配對")
        self.scan_btn.clicked.connect(self._scan)
        form.addRow(self.scan_btn)
        return box

    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("轉碼設定")
        form = QFormLayout(box)

        self.convert_combo = QComboBox()
        self.convert_combo.addItem("FLAC(無損)", "flac")
        self.convert_combo.addItem("M4A / AAC(有損)", "m4a")
        idx = 1 if self.settings.convert_to == "m4a" else 0
        self.convert_combo.setCurrentIndex(idx)
        form.addRow("輸出格式", self.convert_combo)

        self.aac_bitrate = QComboBox()
        for v in ("128k", "160k", "192k", "256k", "320k"):
            self.aac_bitrate.addItem(v)
        self.aac_bitrate.setCurrentText(self.settings.aac_bitrate)
        form.addRow("AAC  bitrate", self.aac_bitrate)

        self.flac_comp = QSpinBox()
        self.flac_comp.setRange(0, 12)
        self.flac_comp.setValue(self.settings.flac_compression)
        form.addRow("FLAC 壓縮等級", self.flac_comp)

        self.sr_combo = QComboBox()
        for v in ("44100", "48000", "88200", "96000"):
            self.sr_combo.addItem(v)
        self.sr_combo.setCurrentText(self.settings.target_sample_rate)
        form.addRow("取樣率(M4A)", self.sr_combo)

        self.policy_combo = QComboBox()
        self.policy_combo.addItem("略過已存在", "skip")
        self.policy_combo.addItem("覆寫", "overwrite")
        self.policy_combo.addItem("自動重新命名", "rename")
        p = {"skip": 0, "overwrite": 1, "rename": 2}.get(self.settings.overwrite_policy, 0)
        self.policy_combo.setCurrentIndex(p)
        form.addRow("同名檔案處理", self.policy_combo)

        self.embed_check = QCheckBox("嵌入歌詞(LRC)")
        self.embed_check.setChecked(self.settings.embed_lyrics)
        form.addRow(self.embed_check)
        return box

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["名稱", "狀態", "音訊", "字幕"])
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
        self.start_btn = QPushButton("開始轉換")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("取消")
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
        box = QGroupBox("FFmpeg 與紀錄")
        lay = QGridLayout(box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(140)
        self.ffmpeg_label = QLabel("")
        self.ffmpeg_label.setTextFormat(Qt.RichText)
        self.ffmpeg_label.setOpenExternalLinks(True)
        self.ffmpeg_btn = QPushButton("指定 ffmpeg.exe...")
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
            self.ffmpeg_label.setText(f"FFmpeg 已找到[{info.source}]: {info.version or '版本未知'}")
            self.ffmpeg_label.setStyleSheet("color: green;")
        else:
            self.ffmpeg_label.setText(
                "找不到 FFmpeg。請至官方網站 <a href=\"%s\">%s</a> 下載,或點右側「指定 ffmpeg.exe...」手動選取。"
                % (FFMPEG_DL_URL, FFMPEG_DL_URL)
            )
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
        d = QFileDialog.getExistingDirectory(self, "選擇音訊資料夾", self.audio_edit.text())
        if d:
            self.audio_edit.setText(d)

    def _choose_subtitle(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "選擇字幕資料夾", self.sub_edit.text())
        if d:
            self.sub_edit.setText(d)

    def _choose_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def _choose_ffmpeg(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "選取 ffmpeg.exe", "", "ffmpeg (ffmpeg.exe)")
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
        self.statusBar().showMessage(f"掃描完成:共 {len(self.pairs)} 筆,已配對 {matched} 筆")

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
            QMessageBox.warning(self, "WAV2FLAC", "尚無任何配對。請先點「掃描並配對」。")
            return
        matched = [p for p in self.pairs if p.status == PairStatus.MATCHED]
        if not matched:
            QMessageBox.warning(self, "WAV2FLAC", "沒有已配對的音訊 + 字幕。")
            return
        info = get_ffmpeg_info(self.settings.ffmpeg_path)
        if not info.ready:
            QMessageBox.critical(
                self, "WAV2FLAC",
                f"找不到 FFmpeg。\n請至官方網站 {FFMPEG_DL_URL} 下載,或於下方「指定 ffmpeg.exe...」手動選取。",
            )
            return
        if not self.out_edit.text():
            QMessageBox.warning(self, "WAV2FLAC", "請先選擇輸出資料夾。")
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
        self.progress.setFormat("轉換中...")

    def _cancel(self) -> None:
        if self.worker:
            self.worker.request_cancel()
            self.statusBar().showMessage("取消中...")

    def _on_progress(self, done: int, total: int, stem: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total} - {stem}")

    def _on_item(self, result) -> None:
        if result.status == "failed":
            self._append_log(f"✘ {os.path.basename(result.audio or '')}:{result.message}")
        elif result.status == "cancelled":
            self._append_log(f"↩ 已取消:{os.path.basename(result.audio or '')}")

    def _on_finished(self, summary) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait(30000)
            self.thread = None
            self.worker.deleteLater()
            self.worker = None
        msg = f"完成:成功 {summary.success} 件、失敗 {summary.failed} 件、略過 {summary.skipped} 件"
        if summary.cancelled:
            msg += ",已取消"
        self.progress.setFormat(msg)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.statusBar().showMessage(self.progress.format())

    def _append_log(self, text: str) -> None:
        self.log_view.append(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

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
