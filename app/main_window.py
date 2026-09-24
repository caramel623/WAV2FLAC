from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt, QSize, QThread
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QComboBox,
    QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QCheckBox, QWidget, QAbstractItemView, QSizePolicy, QRadioButton,
)

from . import __version__, dlsite as dlsite_mod
from .file_matcher import MediaPair, PairStatus, scan_paths
from .ffmpeg_manager import get_ffmpeg_info, FFMPEG_DL_URL
from .settings import Settings
from .settings_dialog import open_settings
from .trash import send_to_trash
from .updater import UpdateWorker, REPO
from .workers import BatchWorker, ConversionConfig, JobItem

_STATUS_TEXT = {
    PairStatus.MATCHED: "已配對",
    PairStatus.MISSING_SUBTITLE: "無字幕(僅轉檔)",
    PairStatus.MISSING_AUDIO: "缺少音訊",
    PairStatus.SKIPPED: "略過",
}


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

        # 模式切換
        mode_row = QHBoxLayout()
        self.mode_manual = QRadioButton("手動配對")
        self.mode_dlsite = QRadioButton("DLsite 模式")
        self._mode_init = True
        self.mode_manual.toggled.connect(self._on_mode_changed)
        if self.settings.mode == "dlsite":
            self.mode_dlsite.setChecked(True)
        else:
            self.mode_manual.setChecked(True)
        self._mode_init = False
        mode_row.addWidget(self.mode_manual)
        mode_row.addWidget(self.mode_dlsite)
        mode_row.addStretch(1)
        form.addRow("模式", mode_row)

        # 手動模式:音訊
        self.audio_edit = QLineEdit(self.settings.source_audio)
        self.audio_edit.setReadOnly(True)
        b_audio = QPushButton("新增...")
        b_audio.clicked.connect(self._choose_audio)
        row_a = QHBoxLayout()
        row_a.addWidget(self.audio_edit, 1)
        row_a.addWidget(b_audio)
        form.addRow("音訊 (WAV 資料夾或檔案)", row_a)
        self.audio_row = form.rowCount() - 1

        # 手動模式:字幕
        self.sub_edit = QLineEdit(self.settings.source_subtitle)
        self.sub_edit.setReadOnly(True)
        b_sub = QPushButton("新增...")
        b_sub.clicked.connect(self._choose_subtitle)
        row_s = QHBoxLayout()
        row_s.addWidget(self.sub_edit, 1)
        row_s.addWidget(b_sub)
        form.addRow("字幕 (VTT/LRC 資料夾或檔案)", row_s)
        self.sub_row = form.rowCount() - 1

        # DLsite 模式:最上層資料夾/壓縮檔
        self.dl_edit = QLineEdit(self.settings.dlsite_input)
        self.dl_edit.setReadOnly(True)
        b_dl = QPushButton("新增...")
        b_dl.clicked.connect(self._choose_dlsite)
        row_d = QHBoxLayout()
        row_d.addWidget(self.dl_edit, 1)
        row_d.addWidget(b_dl)
        form.addRow("DLsite (最上層資料夾/壓縮檔)", row_d)
        self.dl_row = form.rowCount() - 1

        # 輸出(僅手動模式)
        self.out_edit = QLineEdit(self.settings.output_dir)
        b_out = QPushButton("選取...")
        b_out.clicked.connect(self._choose_output)
        row_o = QHBoxLayout()
        row_o.addWidget(self.out_edit, 1)
        row_o.addWidget(b_out)
        form.addRow("輸出資料夾(手動模式)", row_o)
        self.out_row = form.rowCount() - 1
        self._source_form = form

        # 掃描 + 設定
        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("掃描並配對")
        self.scan_btn.clicked.connect(self._scan)
        self.settings_btn = QPushButton("設定…")
        self.settings_btn.clicked.connect(self._open_settings)
        self.update_btn = QPushButton("檢查更新")
        self.update_btn.clicked.connect(self._check_update)
        btn_row.addWidget(self.scan_btn, 1)
        btn_row.addWidget(self.settings_btn)
        btn_row.addWidget(self.update_btn)
        form.addRow(btn_row)

        self._dlsite_scan = dlsite_mod.DlSiteScan()
        self._apply_mode_visibility()
        return box

    def _open_settings(self) -> None:
        if open_settings(self.settings, self):
            self._refresh_ffmpeg()

    def _on_mode_changed(self, _checked: bool = False) -> None:
        if getattr(self, "_mode_init", False):
            return
        self._apply_mode_visibility()

    def _apply_mode_visibility(self) -> None:
        dl = self.mode_dlsite.isChecked()
        self._source_form.setRowVisible(self.audio_row, not dl)
        self._source_form.setRowVisible(self.sub_row, not dl)
        self._source_form.setRowVisible(self.out_row, not dl)
        self._source_form.setRowVisible(self.dl_row, dl)

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
        self.settings.dlsite_input = self.dl_edit.text()
        self.settings.mode = "dlsite" if self.mode_dlsite.isChecked() else "manual"
        self.settings.convert_to = self.convert_combo.currentData()
        self.settings.aac_bitrate = self.aac_bitrate.currentText()
        self.settings.flac_compression = self.flac_comp.value()
        self.settings.target_sample_rate = self.sr_combo.currentText()
        self.settings.overwrite_policy = self.policy_combo.currentData()
        self.settings.embed_lyrics = self.embed_check.isChecked()
        self.settings.save()

    # ----------------------------------------------------------- slots
    def _choose_dlsite(self) -> None:
        base = self.dl_edit.text()
        chosen: List[str] = []
        menu = QMenu(self)
        a_file = QAction("壓縮檔 (.zip / .7z / .rar)", self)
        a_dir = QAction("資料夾(已解開的最上層)", self)
        a_file.triggered.connect(self._pick_dlsite_files)
        a_dir.triggered.connect(self._pick_dlsite_folder)
        menu.addAction(a_file)
        menu.addAction(a_dir)
        # 若輸入欄已有內容,允許直接清除
        if base:
            a_clear = QAction("清除", self)
            a_clear.triggered.connect(lambda: self.dl_edit.clear())
            menu.addSeparator()
            menu.addAction(a_clear)
        pos = QCursor.pos()
        menu.exec(pos)

    def _pick_dlsite_files(self) -> None:
        base = self.dl_edit.text()
        files, _ = QFileDialog.getOpenFileNames(
            self, "選擇 DLsite 商品壓縮檔(.zip/.7z/.rar)", base,
            "壓縮檔 (*.zip *.7z *.rar);;所有檔案 (*)")
        if files:
            self._merge_dl_input(files)

    def _pick_dlsite_folder(self) -> None:
        base = self.dl_edit.text()
        d = QFileDialog.getExistingDirectory(self, "選擇 DLsite 商品最上層資料夾", base)
        if d:
            self._merge_dl_input([d])

    def _merge_dl_input(self, paths: List[str]) -> None:
        base = self.dl_edit.text()
        base_list = [s for s in base.split(os.pathsep) if s] if base else []
        merged: List[str] = []
        seen = set(base_list)
        for p in paths:
            if p and p not in seen:
                merged.append(p)
                seen.add(p)
        result = base_list + merged
        self.dl_edit.setText(os.pathsep.join(result))
        self._scan()

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
        if self.mode_dlsite.isChecked():
            self._scan_dlsite()
        else:
            self._scan_manual()

    def _scan_manual(self) -> None:
        audio_src = [s for s in self.audio_edit.text().split(os.pathsep) if s]
        sub_src = [s for s in self.sub_edit.text().split(os.pathsep) if s]
        out = self.out_edit.text()
        self.pairs = scan_paths(audio_src, sub_src, out)
        self._populate_table()
        matched = sum(1 for p in self.pairs if p.status == PairStatus.MATCHED)
        self.statusBar().showMessage(f"掃描完成:共 {len(self.pairs)} 筆,已配對 {matched} 筆")

    def _scan_dlsite(self) -> None:
        raw = [s for s in self.dl_edit.text().split(os.pathsep) if s]
        # 嚴格限制:只掃描「實際存在」的路徑;舊設定檔裡失效/搬家的路徑會被剔除
        inputs: List[str] = []
        stale: List[str] = []
        seen = set()
        for s in raw:
            if s in seen:
                continue
            seen.add(s)
            if os.path.exists(s):
                inputs.append(s)
            else:
                stale.append(s)
        if stale:
            self.dl_edit.setText(os.pathsep.join(inputs))
            self._append_log(f"    略過 {len(stale)} 個不存在的路徑(可能已搬移/刪除)")
        if not inputs:
            QMessageBox.warning(self, "WAV2FLAC", "請先加入 DLsite 商品最上層資料夾或壓縮檔。")
            return
        self._append_log(f"▶ 掃描 DLsite:{len(inputs)} 個來源(僅限其下子資料夾)")
        scan = dlsite_mod.scan_dlsite(inputs)
        self._dlsite_scan = scan

        # 依商品最上層決定輸出子資料夾(商品/FLAC 或 商品/M4A)
        sub = self.settings.dlsite_output_sub.strip() or self.convert_combo.currentData().upper()
        for pair in scan.pairs:
            base = pair.audio_path or pair.subtitle_path or ""
            # 若來源為壓縮檔,輸出到原壓縮檔所在資料夾(暫存會被清掉)
            origin = self._find_archive_origin(scan, base)
            if origin:
                top = os.path.dirname(os.path.normpath(origin))
            else:
                top = dlsite_mod.product_top(base)
            if top:
                pair.output_dir = os.path.join(top, sub)

        # MP3 清除對照表(音訊檔名 → 同檔名之 MP3 等低損檔)
        trash_map: dict = {}
        if self.settings.trash_mp3:
            mp3_by_stem: dict = {}
            for mp3 in scan.trashable:
                stem = dlsite_mod._norm_stem(os.path.splitext(os.path.basename(mp3))[0])
                mp3_by_stem.setdefault(stem, []).append(mp3)
            for pair in scan.pairs:
                if not pair.audio_path:
                    continue
                stem = dlsite_mod._norm_stem(os.path.splitext(os.path.basename(pair.audio_path))[0])
                if stem in mp3_by_stem:
                    trash_map[os.path.basename(pair.audio_path)] = mp3_by_stem[stem]

        self._dlsite_trash_map = trash_map
        self.pairs = scan.pairs
        self._populate_table()
        matched = len(scan.matched)
        self._append_log(f"    掃描到 {len(scan.pairs)} 筆(已配對 {matched}),"
                         f"發現 {len(scan.trashable)} 個 MP3/低損檔"
                         + (",將清除同檔名 MP3" if trash_map else ""))
        self.statusBar().showMessage(f"DLsite 掃描完成:已配對 {matched} 筆")

    @staticmethod
    def _find_archive_origin(scan: dlsite_mod.DlSiteScan, base: str) -> Optional[str]:
        base = os.path.normpath(base)
        for tmp_root, orig in (scan.archive_origins or {}).items():
            root = os.path.normpath(tmp_root)
            try:
                if os.path.relpath(base, root).split(os.sep)[0] != "..":
                    return orig
            except ValueError:
                continue
        return None

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
        convertible = [p for p in self.pairs if p.can_convert]
        if not convertible:
            QMessageBox.warning(self, "WAV2FLAC", "沒有可轉換的音訊。")
            return
        info = get_ffmpeg_info(self.settings.ffmpeg_path)
        if not info.ready:
            QMessageBox.critical(
                self, "WAV2FLAC",
                f"找不到 FFmpeg。\n請至官方網站 {FFMPEG_DL_URL} 下載,或於下方「指定 ffmpeg.exe...」手動選取。",
            )
            return
        in_dlsite = self.mode_dlsite.isChecked()
        if not in_dlsite and not self.out_edit.text():
            QMessageBox.warning(self, "WAV2FLAC", "請先選擇輸出資料夾。")
            return

        jobs = [JobItem(pair=p, index=i, total=len(convertible)) for i, p in enumerate(convertible)]
        cfg = ConversionConfig(
            convert_to=self.convert_combo.currentData(),
            output_dir="" if in_dlsite else self.out_edit.text(),
            overwrite_policy=self.policy_combo.currentData(),
            aac_bitrate=self.aac_bitrate.currentText(),
            flac_compression=self.flac_comp.value(),
            target_sample_rate=self.sr_combo.currentText(),
            embed_lyrics=self.embed_check.isChecked(),
            ffmpeg_path=info.ffmpeg_path,
            ffprobe_path=info.ffprobe_path,
            trash_map=getattr(self, "_dlsite_trash_map", {}),
        )
        self.worker = BatchWorker(cfg, jobs)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_finished.connect(self._on_item)
        self.worker.log.connect(self._append_log)
        self.worker.dlsite_mp3s.connect(self._on_dlsite_mp3s)
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

    def _on_progress(self, done: int, total: int, stem: str, item_pct: float) -> None:
        self.progress.setRange(0, total)
        base = done - 1 + item_pct / 100.0
        self.progress.setValue(max(0, int(base)))
        self.progress.setFormat(f"{done}/{total} - {stem}({item_pct:.0f}%)")

    def _on_item(self, result) -> None:
        if result.status == "failed":
            self._append_log(f"✘ {os.path.basename(result.audio or '')}:{result.message}")
        elif result.status == "cancelled":
            self._append_log(f"↩ 已取消:{os.path.basename(result.audio or '')}")

    def _on_dlsite_mp3s(self, paths: list) -> None:
        if not self.settings.trash_mp3 or not paths:
            return
        ok, fail = send_to_trash(list(paths))
        for p in list(paths)[:2]:
            self._append_log(f"    ♻ 清除 MP3:{os.path.basename(p)}")
        if len(paths) > 2:
            self._append_log(f"    …共清除 {ok} 個 MP3" + (f"(失敗 {fail})" if fail else ""))

    def _on_finished(self, summary) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait(30000)
            self.thread = None
            self.worker.deleteLater()
            self.worker = None
        dlsite_mod.cleanup_cache()
        msg = f"完成:成功 {summary.success} 件、失敗 {summary.failed} 件、略過 {summary.skipped} 件"
        if summary.cancelled:
            msg += ",已取消"
        self._append_log(f"\n✔ {msg}")
        self.progress.setFormat(msg)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.statusBar().showMessage(self.progress.format())

    def _append_log(self, text: str) -> None:
        self.log_view.append(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # --------------------------------------------------------- 更新
    def _set_updating(self, busy: bool, text: str = "") -> None:
        self._updating = busy
        self.update_btn.setEnabled(not busy)
        if busy:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat(text or "更新中...")

    def _check_update(self) -> None:
        if getattr(self, "_updating", False):
            return
        self._set_updating(True, "檢查更新...")
        self._append_log("▶ 檢查 GitHub 更新...")
        self.update_worker = UpdateWorker(__version__)
        self.update_thread = QThread(self)
        self.update_worker.moveToThread(self.update_thread)
        self.update_thread.started.connect(self.update_worker.run_check)
        self.update_worker.checked.connect(self._on_checked)
        self.update_thread.start()

    def _on_checked(self, info: dict) -> None:
        if self.update_thread:
            self.update_thread.quit()
            self.update_thread.wait(10000)
            self.update_worker.deleteLater()
            self.update_worker = None
            self.update_thread = None
        if info.get("error"):
            self._append_log(f"✘ 檢查更新失敗:{info['error']}")
            self._set_updating(False)
            QMessageBox.critical(
                self, "WAV2FLAC",
                f"檢查更新失敗:\n{info['error']}\n\n請確認網路連線,或前往 {REPO}",
            )
            return
        if not info["has_update"]:
            self._append_log(f"已是最新版本 v{info['current_version']}")
            self._set_updating(False)
            QMessageBox.information(
                self, "檢查更新",
                f"已是最新版本 v{info['current_version']}。",
            )
            return
        if not info["url"]:
            self._append_log(f"發現新版本 v{info['latest_version']},但未找到可下載的 .zip 附件。")
            self._set_updating(False)
            QMessageBox.warning(self, "檢查更新", "發現新版本,但未找到可下載的 .zip 附件,請至發布頁下載。")
            return
        self._pending_update = info
        self._append_log(f"發現新版本 v{info['latest_version']}")
        ans = QMessageBox.question(
            self, "檢查更新",
            f"發現新版本 v{info['latest_version']}(目前 v{info['current_version']})。\n\n"
            "要下載並更新嗎?\n(會下載更新包、重新啟動並覆蓋檔案,完成後自動刪除更新包)",
        )
        if ans == QMessageBox.Yes:
            self._do_update()

    def _do_update(self) -> None:
        info = self._pending_update
        self._set_updating(True, "下載更新 0%")
        self.progress.setValue(0)
        self._append_log(f"▶ 下載更新包 v{info['latest_version']} ...")
        self.update_worker = UpdateWorker(__version__)
        self.update_thread = QThread(self)
        self.update_worker.moveToThread(self.update_thread)
        self.update_worker.progress.connect(self._on_update_progress)
        self.update_worker.log.connect(self._append_log)
        self.update_worker.done.connect(self._on_update_done)
        self.update_thread.started.connect(lambda: self.update_worker.run_update(info["url"]))
        self.update_thread.finished.connect(self.update_thread.deleteLater)
        self.update_thread.start()

    def _on_update_progress(self, pct: int) -> None:
        self.progress.setValue(pct)
        self.progress.setFormat(f"下載更新 {pct}%")

    def _on_update_done(self, res: dict) -> None:
        if res.get("cancelled"):
            self._append_log("↩ 已取消更新。")
            self._set_updating(False)
            self.statusBar().showMessage("已取消更新")

    # --------------------------------------------------------- drag drop
    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        if self.mode_dlsite.isChecked():
            dl: List[str] = []
            for url in e.mimeData().urls():
                path = url.toLocalFile()
                if os.path.isdir(path):
                    dl.append(path)
                elif dlsite_mod.archive.is_archive(path):
                    dl.append(path)
            if dl:
                base = self.dl_edit.text()
                self.dl_edit.setText((base + os.pathsep + os.pathsep.join(dl)).strip(os.pathsep))
            self._scan_dlsite()
            return

        audio: List[str] = []
        subs: List[str] = []
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".vtt") or path.lower().endswith(".lrc"):
                subs.append(path)
            elif path.lower().endswith(".wav"):
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
