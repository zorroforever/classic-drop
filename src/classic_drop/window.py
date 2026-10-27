"""Compact import queue with device-bound previews and explicit publication."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QImage,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from classic_drop.albums import (
    ALBUM_ROLE,
    ARTWORK_ROLE,
    AlbumCardDelegate,
    AlbumSummary,
    group_albums,
)
from classic_drop.engine import ImportResult, PreviewEntry
from classic_drop.worker import Reply, Worker
from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.models.artwork import ArtworkImage
from iOpenPod.app.models.device import ActiveIPod, DeviceCandidate
from iOpenPod.GUI.presentation.icons import glyph_icon
from iPodDB.library import ArtworkPixels, Track

STATUS = {
    "new": "待导入",
    "imported": "已导入",
    "duplicate": "批内重复",
    "possible_duplicate": "疑似重复",
    "error": "无法导入",
}


def button(text: str, glyph: str) -> QPushButton:
    result = QPushButton(text)
    result.setIcon(glyph_icon(glyph, 18, QColor("#30383b")))
    result.setMinimumHeight(32)
    return result


def tool(name: str, glyph: str) -> QToolButton:
    result = QToolButton()
    result.setIcon(glyph_icon(glyph, 19, QColor("#30383b")))
    result.setToolTip(name)
    result.setAccessibleName(name)
    result.setFixedSize(32, 32)
    return result


def readable_size(size: int) -> str:
    return (
        f"{size / (1024**3):.1f} GB"
        if size >= 1024**3
        else f"{size / (1024**2):.1f} MB"
    )


class NumberDelegate(QStyledItemDelegate):
    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        editor = QSpinBox(parent)
        editor.setRange(0, 9999)
        return editor


class MainWindow(QMainWindow):
    request = Signal(str, object)

    def __init__(
        self, *, start_worker: bool = True, directory: Path | None = None
    ) -> None:
        super().__init__()
        self.setWindowTitle("Classic Drop")
        self.resize(1180, 720)
        self.setMinimumSize(940, 580)
        self.setAcceptDrops(True)
        self._entries: tuple[PreviewEntry, ...] = ()
        self._paths: tuple[Path, ...] = ()
        self._active: ActiveIPod | None = None
        self._can_restore = False
        self._busy = False
        self._closing = False
        self._cover_tokens: set[str] = set()
        self._library_tracks: tuple[Track, ...] = ()
        self._albums: tuple[AlbumSummary, ...] = ()
        self._album_artwork: dict[int, QPixmap] = {}
        self._artwork_requests: set[int] = set()
        self._open_album_summary: AlbumSummary | None = None
        self._thread: QThread | None = None
        self.worker: Worker | None = None
        self._build()
        self.set_busy(False)
        if start_worker:
            self._thread = QThread(self)
            self.worker = Worker(directory)
            self.worker.moveToThread(self._thread)
            self.request.connect(self.worker.execute)
            self.worker.succeeded.connect(self._succeeded)
            self.worker.failed.connect(self._failed)
            self.worker.progress.connect(self._progress)
            self.worker.stopped.connect(
                self._thread.quit, Qt.ConnectionType.DirectConnection
            )
            self._thread.finished.connect(self.worker.deleteLater)
            self._thread.finished.connect(self._closed)
            self._thread.start()
            QTimer.singleShot(0, self.refresh)

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel("Classic Drop")
        font = QFont()
        font.setPointSize(21)
        font.setWeight(QFont.Weight.DemiBold)
        title.setFont(font)
        heading.addWidget(title)
        heading.addStretch()
        settings = tool("更多", "settings-sliders")
        menu = QMenu(settings)
        menu.addAction("显示备份和日志", self._reveal_data)
        menu.addAction("关于 Classic Drop", self._about)
        settings.setMenu(menu)
        settings.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        heading.addWidget(settings)
        layout.addLayout(heading)

        device_row = QHBoxLayout()
        self.devices = QComboBox()
        self.devices.setMinimumHeight(34)
        self.devices.addItem("未连接 iPod Classic", None)
        self.devices.currentIndexChanged.connect(self._select_device)
        device_row.addWidget(self.devices, 1)
        self.refresh_button = tool("刷新设备", "refresh")
        self.refresh_button.clicked.connect(self.refresh)
        device_row.addWidget(self.refresh_button)
        self.eject_button = tool("安全弹出", "eject")
        self.eject_button.clicked.connect(lambda: self._submit("eject"))
        device_row.addWidget(self.eject_button)
        layout.addLayout(device_row)
        self.device_info = QLabel("未连接设备")
        self.device_info.setObjectName("muted")
        self.device_info.setWordWrap(True)
        layout.addWidget(self.device_info)

        self.tabs = QTabWidget()
        self.library_page = QWidget()
        library_layout = QVBoxLayout(self.library_page)
        library_toolbar = QHBoxLayout()
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText("搜索标题、艺人或专辑")
        self.library_search.textChanged.connect(self._filter_library)
        library_toolbar.addWidget(self.library_search, 1)
        self.library_count = QLabel("0 首")
        self.library_count.setObjectName("muted")
        library_toolbar.addWidget(self.library_count)
        library_layout.addLayout(library_toolbar)
        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        self.list_mode_button = QToolButton()
        self.list_mode_button.setText("列表")
        self.list_mode_button.setCheckable(True)
        self.album_mode_button = QToolButton()
        self.album_mode_button.setText("专辑")
        self.album_mode_button.setCheckable(True)
        mode_group.addButton(self.list_mode_button)
        mode_group.addButton(self.album_mode_button)
        self.list_mode_button.setChecked(True)
        self.list_mode_button.clicked.connect(lambda: self._set_library_mode("list"))
        self.album_mode_button.clicked.connect(lambda: self._set_library_mode("album"))
        library_toolbar.insertWidget(0, self.list_mode_button)
        library_toolbar.insertWidget(1, self.album_mode_button)
        self.library_table = QTableWidget(0, 7)
        self.library_table.setHorizontalHeaderLabels(
            ["标题", "艺人", "专辑", "专辑艺人", "碟", "曲", "时长"]
        )
        self.library_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.library_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.library_table.setAlternatingRowColors(True)
        self.library_table.setShowGrid(False)
        self.library_table.verticalHeader().hide()
        for column, width in enumerate((190, 130, 180, 130, 45, 45, 70)):
            self.library_table.setColumnWidth(column, width)
        self.library_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.library_stack = QStackedWidget()
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(self.library_table)
        self.library_stack.addWidget(list_page)
        album_page = QWidget()
        album_layout = QVBoxLayout(album_page)
        album_layout.setContentsMargins(0, 0, 0, 0)
        self.album_detail_stack = QStackedWidget()
        self.album_grid = QListWidget()
        self.album_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.album_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.album_grid.setMovement(QListWidget.Movement.Static)
        self.album_grid.setSpacing(10)
        self.album_grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.album_grid.setUniformItemSizes(True)
        self.album_grid.setItemDelegate(AlbumCardDelegate(self._request_artwork, self.album_grid))
        self.album_grid.itemDoubleClicked.connect(self._open_album)
        self.album_detail_stack.addWidget(self.album_grid)
        self.album_detail_page = QWidget()
        album_detail_row = QHBoxLayout(self.album_detail_page)
        album_detail_row.setContentsMargins(8, 8, 8, 8)
        detail_left = QVBoxLayout()
        back_button = button("返回专辑", "skip-back")
        back_button.clicked.connect(lambda: self.album_detail_stack.setCurrentWidget(self.album_grid))
        detail_left.addWidget(back_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.album_detail_cover = QLabel()
        self.album_detail_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.album_detail_cover.setFixedSize(240, 240)
        self.album_detail_cover.setObjectName("cover")
        detail_left.addWidget(self.album_detail_cover)
        self.album_detail_title = QLabel()
        self.album_detail_title.setWordWrap(True)
        self.album_detail_title.setFont(QFont("", 15, QFont.Weight.DemiBold))
        detail_left.addWidget(self.album_detail_title)
        self.album_detail_meta = QLabel()
        self.album_detail_meta.setWordWrap(True)
        self.album_detail_meta.setObjectName("muted")
        detail_left.addWidget(self.album_detail_meta)
        detail_left.addStretch()
        album_detail_row.addLayout(detail_left, 0)
        self.album_track_table = QTableWidget(0, 4)
        self.album_track_table.setHorizontalHeaderLabels(["曲", "标题", "艺人", "时长"])
        self.album_track_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.album_track_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.album_track_table.setAlternatingRowColors(True)
        self.album_track_table.setShowGrid(False)
        self.album_track_table.verticalHeader().hide()
        self.album_track_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        album_detail_row.addWidget(self.album_track_table, 1)
        self.album_detail_stack.addWidget(self.album_detail_page)
        album_layout.addWidget(self.album_detail_stack)
        self.library_stack.addWidget(album_page)
        library_layout.addWidget(self.library_stack, 1)
        self.tabs.addTab(self.library_page, "iPod 曲库")

        self.import_page = QWidget()
        import_layout = QVBoxLayout(self.import_page)
        toolbar = QHBoxLayout()
        self.files_button = button("添加文件", "plus")
        self.files_button.clicked.connect(self._choose_files)
        self.folder_button = button("添加文件夹", "folder")
        self.folder_button.clicked.connect(self._choose_folder)
        self.remove_button = tool("移出队列", "minus")
        self.remove_button.clicked.connect(self._remove)
        toolbar.addWidget(self.files_button)
        toolbar.addWidget(self.folder_button)
        toolbar.addWidget(self.remove_button)
        toolbar.addStretch()
        self.count_label = QLabel("0 首")
        self.count_label.setObjectName("muted")
        toolbar.addWidget(self.count_label)
        import_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["", "标题", "艺人", "专辑", "专辑艺人", "碟", "曲", "状态"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.horizontalHeader().setMinimumSectionSize(34)
        for column, width in enumerate((34, 175, 110, 140, 110, 40, 40, 105)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setItemDelegateForColumn(5, NumberDelegate(self.table))
        self.table.setItemDelegateForColumn(6, NumberDelegate(self.table))
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemChanged.connect(self._queue_changed)
        splitter.addWidget(self.table)
        details = QWidget()
        details.setMinimumWidth(210)
        details.setMaximumWidth(280)
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setFixedSize(200, 200)
        self.cover.setObjectName("cover")
        detail_layout.addWidget(self.cover)
        cover_actions = QHBoxLayout()
        self.cover_button = button("选择封面", "photo")
        self.cover_button.clicked.connect(self._choose_cover)
        cover_actions.addWidget(self.cover_button)
        self.clear_cover_button = tool("移除封面", "x")
        self.clear_cover_button.clicked.connect(self._clear_cover)
        cover_actions.addWidget(self.clear_cover_button)
        cover_actions.addStretch()
        detail_layout.addLayout(cover_actions)
        self.track_title = QLabel("未选择音乐")
        self.track_title.setWordWrap(True)
        self.track_title.setFont(QFont("", 14, QFont.Weight.DemiBold))
        detail_layout.addWidget(self.track_title)
        self.track_details = QLabel()
        self.track_details.setWordWrap(True)
        self.track_details.setObjectName("muted")
        detail_layout.addWidget(self.track_details)
        detail_layout.addStretch()
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.source_label.setObjectName("muted")
        self.source_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        detail_layout.addWidget(self.source_label)
        splitter.addWidget(details)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([850, 230])
        import_layout.addWidget(splitter, 1)
        self.tabs.addTab(self.import_page, "待导入")
        layout.addWidget(self.tabs, 1)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(5)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        footer = QHBoxLayout()
        self.status = QLabel("就绪")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(40)
        footer.addWidget(self.status, 1)
        self.restore_button = button("撤销上次导入", "skip-back")
        self.restore_button.clicked.connect(self._restore)
        footer.addWidget(self.restore_button)
        self.cancel_button = button("取消", "x")
        self.cancel_button.clicked.connect(self._cancel)
        footer.addWidget(self.cancel_button)
        self.import_button = button("导入所选", "music")
        self.import_button.setObjectName("primary")
        self.import_button.clicked.connect(self._commit)
        footer.addWidget(self.import_button)
        layout.addLayout(footer)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f5f6f7; color: #24282a; }
            QLabel#muted { color: #697377; font-size: 12px; }
            QPushButton, QToolButton, QComboBox {
                background: #ffffff; border: 1px solid #d5dadc;
                border-radius: 5px; padding: 4px 9px;
            }
            QToolButton { padding: 4px; }
            QPushButton:hover, QToolButton:hover { background: #eaf0f0; }
            QPushButton:disabled, QToolButton:disabled, QComboBox:disabled { color: #a2aaad; }
            QPushButton#primary { background: #15685b; border-color: #15685b; color: white; font-weight: 600; }
            QPushButton#primary:disabled { background: #d5dfdc; border-color: #d5dfdc; color: #899792; }
            QTableWidget { background: #ffffff; alternate-background-color: #f7f9f9;
                border: 1px solid #d9dfe1; selection-background-color: #d8ece6; selection-color: #193d33; }
            QHeaderView::section { background: #edf0f1; padding: 8px 4px; border: 0;
                border-bottom: 1px solid #d9dfe1; color: #596368; font-size: 12px; }
            QProgressBar { border: 0; background: #e0e5e6; border-radius: 2px; }
            QProgressBar::chunk { background: #248271; border-radius: 2px; }
            QLabel#cover { background: #e8ecee; border: 1px solid #dce2e4; }
            QMenu { background: white; }
        """)
        self._show_cover(None)

    def _submit(self, command: str, payload: object = None) -> None:
        if self._busy or self.worker is None:
            return
        self.worker.cancelled.clear()
        self.set_busy(True)
        self.status.setText(
            {
                "discover": "正在查找设备",
                "select": "正在读取曲库",
                "preview": "正在检查音乐",
                "commit": "正在准备导入",
                "restore": "正在恢复上次曲库",
                "eject": "正在弹出设备",
            }.get(command, "正在处理")
        )
        self.request.emit(command, payload)

    def refresh(self) -> None:
        self._submit("discover")

    def _select_device(self, index: int) -> None:
        candidate = self.devices.itemData(index)
        if candidate is not None:
            self._submit("select", candidate)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        active = self._active is not None
        self.devices.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.eject_button.setEnabled(active and not busy)
        self.files_button.setEnabled(active and not busy)
        self.folder_button.setEnabled(active and not busy)
        self.table.setEnabled(not busy)
        self.library_table.setEnabled(not busy)
        self.remove_button.setEnabled(bool(self._entries) and not busy)
        self.cover_button.setEnabled(bool(self.table.selectedItems()) and not busy)
        self.clear_cover_button.setEnabled(
            bool(self.table.selectedItems()) and not busy
        )
        self.restore_button.setEnabled(self._can_restore and not busy)
        self.cancel_button.setEnabled(busy)
        self.import_button.setEnabled(
            active and not busy and self._selected_count() > 0
        )
        self.progress.setRange(0, 0 if busy else 1)
        if not busy:
            self.progress.setValue(0)

    def _selected_count(self) -> int:
        return sum(
            self._item(row, 0).checkState() == Qt.CheckState.Checked
            for row in range(self.table.rowCount())
        )

    def _item(self, row: int, column: int) -> QTableWidgetItem:
        item = self.table.item(row, column)
        if item is None:
            raise RuntimeError(f"missing table item {row},{column}")
        return item

    def show_entries(self, entries: tuple[PreviewEntry, ...]) -> None:
        self._entries = entries
        self.table.blockSignals(True)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            checked = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if entry.status not in ("error", "duplicate"):
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            checked.setFlags(flags)
            checked.setCheckState(
                Qt.CheckState.Checked if entry.selected else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, 0, checked)
            values = [
                entry.title or entry.path.stem,
                entry.artist,
                entry.album,
                entry.album_artist,
                str(entry.disc_number),
                str(entry.track_number),
                STATUS[entry.status],
            ]
            if entry.status == "new" and entry.mode == "convert":
                values[-1] = "转换后导入"
            for col, text in enumerate(values, 1):
                item = QTableWidgetItem(text)
                if col == 7 or entry.status == "error":
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    )
                item.setToolTip(entry.detail if col == 7 else text)
                if col == 7:
                    item.setForeground(
                        QColor("#ac4a32" if entry.status == "error" else "#59776e")
                    )
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        if entries:
            self.table.selectRow(0)
        else:
            self._selection_changed()
        self._queue_changed()

    def _update_library_table(self) -> None:
        tracks = tuple(getattr(getattr(self._active, "library", None), "tracks", ()))
        device_id = getattr(
            getattr(getattr(self._active, "candidate", None), "id", None),
            "value",
            None,
        )
        previous_device_id = getattr(self, "_library_device_id", None)
        library_changed = tracks != self._library_tracks or device_id != previous_device_id
        if library_changed:
            self._album_artwork.clear()
            self._artwork_requests.clear()
            self.album_detail_stack.setCurrentWidget(self.album_grid)
            self._open_album_summary = None
        self._library_device_id = device_id
        self._library_tracks = tracks
        self.library_table.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            seconds = max(0, track.length_ms // 1000)
            values = (
                track.title,
                track.artist,
                track.album,
                track.album_artist or track.artist,
                str(track.metadata.disc_number or 0),
                str(track.track_number or 0),
                f"{seconds // 60}:{seconds % 60:02d}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(
                    item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                self.library_table.setItem(row, column, item)
        self.library_count.setText(f"{len(tracks):,} 首")
        if library_changed:
            self._albums = group_albums(tracks)
            self._update_album_grid()
        self._filter_library(self.library_search.text())

    def _set_library_mode(self, mode: str) -> None:
        album_mode = mode == "album"
        self.list_mode_button.setChecked(not album_mode)
        self.album_mode_button.setChecked(album_mode)
        self.library_stack.setCurrentIndex(1 if album_mode else 0)
        self.album_detail_stack.setCurrentWidget(self.album_grid)
        self._open_album_summary = None
        self._filter_library(self.library_search.text())

    def _update_album_grid(self) -> None:
        self.album_grid.clear()
        for album in self._albums:
            item = QListWidgetItem()
            item.setSizeHint(QSize(190, 258))
            item.setData(ALBUM_ROLE, album)
            if album.artwork_id in self._album_artwork:
                item.setData(ARTWORK_ROLE, self._album_artwork[album.artwork_id])
            self.album_grid.addItem(item)

    def _open_album(self, item: QListWidgetItem) -> None:
        album = item.data(ALBUM_ROLE)
        if not isinstance(album, AlbumSummary):
            return
        self._open_album_summary = album
        self.album_detail_title.setText(album.title or "未知专辑")
        meta = album.artist or "未知艺人"
        if album.year:
            meta += f"  ·  {album.year}"
        meta += f"\n{album.track_count} 首  ·  {album.duration_ms // 60000}:{album.duration_ms // 1000 % 60:02d}"
        self.album_detail_meta.setText(meta)
        pixmap = self._album_artwork.get(album.artwork_id)
        if pixmap is None:
            self.album_detail_cover.setPixmap(
                glyph_icon("album", 120, QColor("#899497")).pixmap(QSize(120, 120))
            )
            self._request_artwork(album.artwork_id)
        else:
            self.album_detail_cover.setPixmap(
                pixmap.scaled(230, 230, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        self.album_track_table.setRowCount(len(album.tracks))
        for row, track in enumerate(album.tracks):
            values = (
                str(track.track_number or row + 1),
                track.title,
                track.artist,
                f"{max(0, track.length_ms) // 60000}:{max(0, track.length_ms) // 1000 % 60:02d}",
            )
            for column, value in enumerate(values):
                self.album_track_table.setItem(row, column, QTableWidgetItem(value))
        self.album_detail_stack.setCurrentWidget(self.album_detail_page)

    def _request_artwork(self, artwork_id: int) -> None:
        if artwork_id <= 0 or artwork_id in self._artwork_requests or self.worker is None:
            return
        self._artwork_requests.add(artwork_id)
        self.request.emit("artwork", artwork_id)

    def _show_album_artwork(self, artwork: ArtworkImage | None) -> None:
        if artwork is None:
            return
        image = QImage(
            artwork.rgb888,
            artwork.width,
            artwork.height,
            artwork.width * 3,
            QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image)
        self._album_artwork[artwork.artwork_id] = pixmap
        for row in range(self.album_grid.count()):
            item = self.album_grid.item(row)
            album = item.data(ALBUM_ROLE)
            if isinstance(album, AlbumSummary) and album.artwork_id == artwork.artwork_id:
                item.setData(ARTWORK_ROLE, pixmap)
        if (
            self.album_detail_stack.currentWidget() is self.album_detail_page
            and self._open_album_summary is not None
            and self._open_album_summary.artwork_id == artwork.artwork_id
        ):
            self.album_detail_cover.setPixmap(
                pixmap.scaled(
                    230,
                    230,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.album_grid.viewport().update()

    def _filter_library(self, text: str) -> None:
        query = text.casefold().strip()
        for row, track in enumerate(self._library_tracks):
            haystack = "\n".join(
                (track.title, track.artist, track.album, track.album_artist)
            ).casefold()
            self.library_table.setRowHidden(row, bool(query and query not in haystack))
        for row, album in enumerate(self._albums):
            haystack = "\n".join(
                (
                    album.title,
                    album.artist,
                    str(album.year),
                    *(value for track in album.tracks for value in (track.title, track.artist)),
                )
            ).casefold()
            self.album_grid.item(row).setHidden(bool(query and query not in haystack))

    def edited_entries(self) -> tuple[PreviewEntry, ...]:
        return tuple(
            replace(
                entry,
                selected=self._item(row, 0).checkState() == Qt.CheckState.Checked,
                title=self._item(row, 1).text(),
                artist=self._item(row, 2).text(),
                album=self._item(row, 3).text(),
                album_artist=self._item(row, 4).text(),
                disc_number=int(self._item(row, 5).text() or "0"),
                track_number=int(self._item(row, 6).text() or "0"),
            )
            for row, entry in enumerate(self._entries)
        )

    def _queue_changed(self) -> None:
        count = self._selected_count()
        self.count_label.setText(f"{count} / {len(self._entries)} 首")
        self.import_button.setText(f"导入 {count} 首" if count else "导入所选")
        self.import_button.setEnabled(
            self._active is not None and count > 0 and not self._busy
        )

    def _show_cover(self, artwork: ArtworkPixels | None) -> None:
        if artwork is None:
            self.cover.setPixmap(
                glyph_icon("album", 64, QColor("#9aa7ad")).pixmap(QSize(64, 64))
            )
        else:
            image = QImage(
                artwork.rgb888,
                artwork.width,
                artwork.height,
                artwork.width * 3,
                QImage.Format.Format_RGB888,
            ).copy()
            self.cover.setPixmap(
                QPixmap.fromImage(image).scaled(
                    198,
                    198,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _selection_changed(self) -> None:
        row = self.table.currentRow()
        selected = bool(self.table.selectedItems())
        self.cover_button.setEnabled(selected and not self._busy)
        self.clear_cover_button.setEnabled(selected and not self._busy)
        if row < 0 or row >= len(self._entries):
            self._show_cover(None)
            self.track_title.setText("未选择音乐")
            self.track_details.clear()
            self.source_label.clear()
            return
        entry = self._entries[row]
        self._show_cover(entry.artwork)
        self.track_title.setText(entry.title or entry.path.stem)
        seconds = entry.length_ms // 1000
        self.track_details.setText(
            f"{entry.artist}\n{entry.album}\n\n{seconds // 60}:{seconds % 60:02d}  ·  {readable_size(entry.size_bytes)}\n{STATUS[entry.status]}"
        )
        self.source_label.setText(str(entry.path))
        self.source_label.setToolTip(entry.detail or str(entry.path))

    def _choose_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "选择音乐",
            "",
            "音乐 (*.mp3 *.m4a *.flac *.wav *.aif *.aiff *.aac *.ogg *.opus *.wma *.ape *.wv);;所有文件 (*)",
        )
        if paths:
            self._add_paths(tuple(Path(p) for p in paths))

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择专辑或音乐文件夹")
        if path:
            self._add_paths((Path(path),))

    def _add_paths(self, paths: tuple[Path, ...]) -> None:
        self._paths = tuple(dict.fromkeys((*self._paths, *paths)))
        self._submit("preview", self._paths)

    def _remove(self) -> None:
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        self.show_entries(
            tuple(
                e for row, e in enumerate(self.edited_entries()) if row not in selected
            )
        )
        self._paths = tuple(e.path for e in self._entries)

    def _choose_cover(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择专辑封面", "", "图片 (*.jpg *.jpeg *.png *.webp)"
        )
        if path:
            self._cover_tokens = {
                self._entries[i.row()].token
                for i in self.table.selectionModel().selectedRows()
            }
            self._submit("cover", Path(path))

    def _clear_cover(self) -> None:
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        self.show_entries(
            tuple(
                replace(e, artwork=None) if row in selected else e
                for row, e in enumerate(self.edited_entries())
            )
        )

    def _commit(self) -> None:
        try:
            self._submit("commit", self.edited_entries())
        except ValueError as error:
            QMessageBox.warning(self, "曲号无效", str(error))

    def _restore(self) -> None:
        if (
            QMessageBox.question(
                self, "撤销上次导入", "恢复上次导入前的曲库，并移除该次导入的音乐？"
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._submit("restore")

    def _cancel(self) -> None:
        if self.worker:
            self.worker.cancelled.set()
        self.status.setText("正在取消，等待当前步骤结束")
        self.cancel_button.setEnabled(False)

    def _succeeded(self, command: str, reply: Reply) -> None:
        if self._closing:
            self.request.emit("close", None)
            return
        if command == "artwork":
            self._show_album_artwork(cast("ArtworkImage | None", reply.value))
            return
        previous_active = self._active
        self._active, self._can_restore = reply.active, reply.can_restore
        self.set_busy(False)
        if command == "discover":
            candidates = cast("tuple[DeviceCandidate, ...]", reply.value)
            self.devices.blockSignals(True)
            self.devices.clear()
            self.devices.addItem(
                "选择 iPod Classic" if candidates else "未连接 iPod Classic", None
            )
            for candidate in candidates:
                self.devices.addItem(
                    f"{candidate.display_name} · {candidate.profile_name}", candidate.id
                )
            self.devices.blockSignals(False)
            if len(candidates) == 1:
                self.devices.setCurrentIndex(1)
            elif self._active:
                for index in range(self.devices.count()):
                    if self.devices.itemData(index) == self._active.candidate.id:
                        self.devices.setCurrentIndex(index)
                        break
            if self._active is None:
                self._update_library_table()
            self.status.setText(f"找到 {len(candidates)} 台设备")
        elif command == "select":
            same_device = bool(
                previous_active
                and self._active
                and previous_active.candidate.id == self._active.candidate.id
            )
            if not same_device:
                self._paths = ()
                self.show_entries(())
            self._update_library_table()
            self.tabs.setCurrentWidget(self.library_page)
            self.status.setText("曲库已读取")
        elif command == "preview":
            old = {entry.path: entry for entry in self.edited_entries()}
            incoming = tuple(cast("tuple[PreviewEntry, ...]", reply.value))
            merged = tuple(
                replace(
                    entry,
                    title=old[entry.path].title,
                    artist=old[entry.path].artist,
                    album=old[entry.path].album,
                    album_artist=old[entry.path].album_artist,
                    disc_number=old[entry.path].disc_number,
                    track_number=old[entry.path].track_number,
                    selected=old[entry.path].selected,
                    artwork=old[entry.path].artwork,
                )
                if entry.path in old
                else entry
                for entry in incoming
            )
            self.show_entries(merged)
            self.tabs.setCurrentWidget(self.import_page)
            self.status.setText(
                "预览就绪" if self._entries else "所选位置没有支持的音乐文件"
            )
        elif command == "cover":
            artwork = cast("ArtworkPixels", reply.value)
            self.show_entries(
                tuple(
                    replace(e, artwork=artwork) if e.token in self._cover_tokens else e
                    for e in self.edited_entries()
                )
            )
            self.status.setText("封面已更新")
        elif command == "commit":
            result = cast("ImportResult", reply.value)
            self._paths = ()
            self.show_entries(())
            self._update_library_table()
            self.status.setText(f"已导入 {result.added} 首")
            if result.warnings:
                QMessageBox.warning(
                    self, "导入完成，需留意", "\n".join(result.warnings)
                )
        elif command == "restore":
            self._paths = ()
            self.show_entries(())
            self._update_library_table()
            self.status.setText("已恢复上次导入前的曲库")
        elif command == "eject":
            self._paths = ()
            self.show_entries(())
            self._update_library_table()
            self.devices.blockSignals(True)
            self.devices.clear()
            self.devices.addItem("设备已弹出", None)
            self.devices.blockSignals(False)
            self.status.setText("可以断开 iPod")
        self._update_device_info()
        self.set_busy(self._busy)

    def _failed(self, command: str, message: str, reply: Reply) -> None:
        if self._closing:
            self.request.emit("close", None)
            return
        if command == "artwork":
            return
        self._active, self._can_restore = reply.active, reply.can_restore
        self._update_library_table()
        self.set_busy(False)
        self.status.setText("操作已取消" if "取消" in message else "操作未完成")
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Classic Drop")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(message[:400])
        if len(message) > 400:
            dialog.setDetailedText(message)
        if "取消" not in message:
            dialog.exec()
        self._update_device_info()

    def _update_device_info(self) -> None:
        if self._active:
            active = self._active
            self.device_info.setText(
                f"{active.profile.display_name}  ·  {active.profile.model_number}  ·  {len(active.library.tracks):,} 首  ·  可用 {readable_size(active.candidate.available_bytes)}"
            )
        else:
            self.device_info.setText("未连接设备")

    def _progress(self, progress: WriteProgress) -> None:
        if self._closing:
            return
        phase = progress.phase
        label = "正在写入并验证"
        if phase == "inspect":
            label = "正在检查音乐"
        elif phase == "history":
            label = "正在保留播放历史"
        elif phase.startswith("database."):
            label = "正在准备曲库和封面"
        elif "recover" in phase:
            label = "正在恢复曲库"
        self.status.setText(f"{label}  {progress.current_item}")
        if progress.total and progress.completed is not None:
            self.progress.setRange(0, progress.total)
            self.progress.setValue(progress.completed)
        else:
            self.progress.setRange(0, 0)

    def _reveal_data(self) -> None:
        directory = (
            self.worker.directory
            if self.worker and self.worker.directory
            else Path.home() / "Library/Application Support/Classic Drop"
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "关于 Classic Drop",
            "Classic Drop 0.1.0\n\niPod Classic 音乐导入工具\n基于 iOpenPod 2.0.15\nGPL-3.0-or-later\n\n源码与第三方许可见 CLASSIC_DROP.md。",
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if (
            self._active
            and not self._busy
            and event.mimeData().hasUrls()
            and all(u.isLocalFile() for u in event.mimeData().urls())
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if self._active and not self._busy:
            paths = tuple(
                Path(u.toLocalFile())
                for u in event.mimeData().urls()
                if u.isLocalFile()
            )
            if paths:
                self._add_paths(paths)
                event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread and self._thread.isRunning():
            event.ignore()
            self._closing = True
            if self._busy:
                self._cancel()
            else:
                self.request.emit("close", None)
            self.setEnabled(False)
        else:
            event.accept()

    def _closed(self) -> None:
        self.close()
