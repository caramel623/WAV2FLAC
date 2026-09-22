from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QCheckBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from . import ffmpeg_manager
from .ffmpeg_manager import FFMPEG_DL_URL
from .settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._s = settings
        self.setWindowTitle("設定")
        self.resize(560, 440)
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_ffmpeg_tab(), "FFmpeg")
        tabs.addTab(self._build_archive_tab(), "封存格式")
        tabs.addTab(self._build_dlsite_tab(), "DLsite 模式")
        lay.addWidget(tabs, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.ok_btn = QPushButton("儲存")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self._ok)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.ok_btn)
        btns.addWidget(cancel_btn)
        lay.addLayout(btns)

    # ---------------- FFmpeg tab
    def _build_ffmpeg_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ffmpeg_edit = QLineEdit(self._s.ffmpeg_path)
        self.ffmpeg_edit.setReadOnly(True)
        row = QHBoxLayout()
        row.addWidget(self.ffmpeg_edit, 1)
        pick = QPushButton("選取...")
        pick.clicked.connect(self._pick_ffmpeg)
        row.addWidget(pick)
        f.addRow("ffmpeg.exe", row)
        self.ffmpeg_status = QLabel("")
        f.addRow("", self.ffmpeg_status)
        hint = QLabel(f"找不到時可至 <a href='{FFMPEG_DL_URL}'>官方下載</a> 。")
        hint.setTextFormat(Qt.RichText)
        hint.setOpenExternalLinks(True)
        f.addRow(hint)
        self._refresh_status()
        return w

    def _pick_ffmpeg(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "選取 ffmpeg.exe", "", "ffmpeg (ffmpeg.exe)")
        if f:
            self.ffmpeg_edit.setText(f)
            self._refresh_status()

    def _refresh_status(self) -> None:
        info = ffmpeg_manager.get_ffmpeg_info(self.ffmpeg_edit.text())
        if info.ready:
            self.ffmpeg_status.setText(f"已找到[{info.source}]: {info.version or '版本未知'}")
            self.ffmpeg_status.setStyleSheet("color: green;")
        else:
            self.ffmpeg_status.setText("路徑無效或未找到。")
            self.ffmpeg_status.setStyleSheet("color: red;")

    # ---------------- Archive tab
    def _build_archive_tab(self) -> QWidget:
        import importlib
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("支援的壓縮格式(需安裝對應套件;ZIP 內建支援):"))
        rows = QVBoxLayout()
        for mod, label in (
            ("zipfile", "ZIP(內建)"),
            ("py7zr", "7Z (.7z)"),
            ("rarfile", "RAR (.rar)"),
        ):
            try:
                importlib.import_module(mod)
                ok = True
            except ImportError:
                ok = False
            item = QLabel(f"{'✓' if ok else '✗'} {label}")
            item.setStyleSheet("color: green;" if ok else "color: gray;")
            rows.addWidget(item)
        lay.addLayout(rows)
        note = QLabel("未安裝的格式可執行:  pip install py7zr rarfile")
        note.setStyleSheet("color: gray;")
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    # ---------------- DLsite tab
    def _build_dlsite_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.trash_mp3 = QCheckBox("轉換後清除 MP3 等低損檔(丟回收桶)")
        self.trash_mp3.setChecked(self._s.trash_mp3)
        f.addRow(self.trash_mp3)
        self.dl_sub = QLineEdit(self._s.dlsite_output_sub)
        self.dl_sub.setPlaceholderText("留空 = 輸出到 商品/FLAC(或 M4A)")
        f.addRow("輸出子資料夾", self.dl_sub)
        info = QLabel("DLsite 模式:選取最上層資料夾或壓縮檔,自動探索 WAV/VTT/LRC,依檔名配對,並輸出到 商品/FLAC。")
        info.setWordWrap(True)
        f.addRow(info)
        return w

    # ---------------- actions
    def _ok(self) -> None:
        self._s.ffmpeg_path = self.ffmpeg_edit.text()
        self._s.trash_mp3 = self.trash_mp3.isChecked()
        self._s.dlsite_output_sub = self.dl_sub.text().strip()
        self._s.save()
        self.accept()


def open_settings(settings: Settings, parent: QWidget) -> bool:
    dlg = SettingsDialog(settings, parent)
    return dlg.exec() == QDialog.Accepted
