"""Compact import queue with device-bound previews and explicit publication."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    QEvent,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QKeySequence,
    QPalette,
    QPixmap,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTableWidgetItem,
    QToolButton,
)

from classic_drop.albums import (
    ALBUM_ROLE,
    ARTWORK_ROLE,
    AlbumSummary,
    group_albums,
)
from classic_drop.engine import ImportResult, PreviewEntry
from classic_drop.i18n import (
    SYSTEM_LANGUAGE,
    get_language_manager,
    render_text,
    song_count,
    tr,
)
from classic_drop.import_view import ImportView
from classic_drop.library_view import LibraryCell, LibraryView
from classic_drop.presentation import STYLE, tool
from classic_drop.shell import WorkspaceShell
from classic_drop.worker import Reply, Worker
from iOpenPod.app.display_text import SourceText, source_text
from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.models.artwork import ArtworkImage
from iOpenPod.app.models.device import ActiveIPod, DeviceCandidate
from iOpenPod.GUI.presentation.icons import glyph_icon
from iPodDB.library import ArtworkPixels, Track

STATUS = {
    "new": "Queued",
    "imported": "Already imported",
    "duplicate": "Duplicate in batch",
    "possible_duplicate": "Possible duplicate",
    "error": "Cannot import",
}


def readable_size(size: int) -> str:
    return (
        f"{size / (1024**3):.1f} GB"
        if size >= 1024**3
        else f"{size / (1024**2):.1f} MB"
    )


class MainWindow(QMainWindow):
    request = Signal(str, object)

    def __init__(
        self, *, start_worker: bool = True, directory: Path | None = None
    ) -> None:
        super().__init__()
        application = cast("QApplication | None", QApplication.instance())
        if application is None:
            raise RuntimeError("Classic Drop requires a QApplication")
        self._language_manager = get_language_manager(application, directory)
        self._language_manager.languageChanged.connect(self._language_changed)
        self.setWindowTitle("Classic Drop")
        self.resize(1180, 760)
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
        self._inspector_artwork_id = 0
        self._device_placeholder = "No iPod Classic connected"
        self._status_message: str = "Ready"
        self._current_progress: WriteProgress | None = None
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
        self.shell = WorkspaceShell()
        self.setCentralWidget(self.shell)
        self.library_view = LibraryView(self)
        self.import_view = ImportView(self)
        self.library_page = self.library_view
        self.import_page = self.import_view
        self.library_search = self.library_view.library_search
        self.library_count = self.library_view.library_count
        self.list_mode_button = self.library_view.list_mode_button
        self.album_mode_button = self.library_view.album_mode_button
        self.library_table = self.library_view.library_table
        self.library_stack = self.library_view.library_stack
        self.library_list_page = self.library_view.library_list_page
        self.library_album_page = self.library_view.library_album_page
        self.album_detail_stack = self.library_view.album_detail_stack
        self.album_grid = self.library_view.album_grid
        self.album_detail_page = self.library_view.album_detail_page
        self.back_button = self.library_view.back_button
        self.album_detail_cover = self.library_view.album_detail_cover
        self.album_detail_title = self.library_view.album_detail_title
        self.album_detail_meta = self.library_view.album_detail_meta
        self.album_track_table = self.library_view.album_track_table
        self.files_button = self.import_view.files_button
        self.folder_button = self.import_view.folder_button
        self.remove_button = self.import_view.remove_button
        self.count_label = self.import_view.count_label
        self.table = self.import_view.table
        self.queue_stack = self.import_view.queue_stack
        self.queue_details = self.import_view.queue_details
        self.cover = self.import_view.cover
        self.cover_button = self.import_view.cover_button
        self.clear_cover_button = self.import_view.clear_cover_button
        self.track_title = self.import_view.track_title
        self.track_details = self.import_view.track_details
        self.source_label = self.import_view.source_label
        self.library_empty_page = self.library_view.library_empty_page
        self.library_empty_title = self.library_view.library_empty_title
        self.library_empty_detail = self.library_view.library_empty_detail
        self.queue_empty_page = self.import_view.queue_empty_page
        self.queue_empty_title = self.import_view.queue_empty_title
        self.queue_empty_detail = self.import_view.queue_empty_detail
        self.library_inspector_title = self.library_view.inspector_title
        self.library_inspector_details = self.library_view.inspector_details
        self.inspector_stack = self.shell.inspectors
        self.inspector_stack.addWidget(self.library_view.inspector)
        self.inspector_stack.addWidget(self.queue_details)
        self.pages = self.shell.pages
        self.recovery_page = self.shell.recovery_page
        self.pages.addWidget(self.library_page)
        self.pages.addWidget(self.import_page)
        self.pages.addWidget(self.recovery_page)
        self.sidebar = self.shell.sidebar
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.pages.currentChanged.connect(self._workspace_changed)
        self.heading_title = self.shell.title
        self.toolbar = self.shell.toolbar
        self.library_view.library_search.setMaximumWidth(280)
        self.library_view.library_search.setMinimumWidth(160)
        self.library_controls_action = self.toolbar.addWidget(
            self.library_view.controls
        )
        self.inspector_button = self.shell.inspector_button
        self.inspector_button.toggled.connect(self._set_inspector_visible)
        self.toolbar.addWidget(self.inspector_button)
        self.settings_button = tool("Settings", "settings-sliders")
        menu = QMenu(self.settings_button)
        self.backups_action = menu.addAction("Show backups and logs", self._reveal_data)
        self.about_action = menu.addAction("About Classic Drop", self._about)
        self.settings_menu = menu.addMenu("Settings")
        self.general_menu = self.settings_menu.addMenu("General")
        self.language_menu = self.general_menu.addMenu("Language")
        language_group = QActionGroup(self)
        language_group.setExclusive(True)
        self.language_actions = {}
        for language, label in (
            (SYSTEM_LANGUAGE, "Follow system"),
            ("en", "English"),
            ("zh_CN", "简体中文"),
            ("ja_JP", "日本語"),
        ):
            action = self.language_menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, selected=language: (
                    self._language_manager.set_language(selected)
                )
            )
            language_group.addAction(action)
            self.language_actions[language] = action
        self.settings_button.setMenu(menu)
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu.setTitle("Classic Drop")
        self.menuBar().addMenu(menu)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self.quit_action = menu.addAction("Quit Classic Drop", self.close)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.toolbar.addWidget(self.settings_button)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        self.setUnifiedTitleAndToolBarOnMac(True)
        device_row = QHBoxLayout()
        self.devices = QComboBox()
        self.devices.setMinimumHeight(34)
        self.devices.addItem("No iPod Classic connected", None)
        self.devices.currentIndexChanged.connect(self._select_device)
        device_row.addWidget(self.devices, 1)
        self.refresh_button = tool("Refresh devices", "refresh")
        self.refresh_button.clicked.connect(self.refresh)
        device_row.addWidget(self.refresh_button)
        self.eject_button = tool("Safely eject", "eject")
        self.eject_button.clicked.connect(lambda: self._submit("eject"))
        device_row.addWidget(self.eject_button)
        self.shell.device_layout.addLayout(device_row)
        self.device_info = QLabel("No device connected")
        self.device_info.setObjectName("muted")
        self.device_info.setWordWrap(True)
        self.shell.device_layout.addWidget(self.device_info)

        self.progress = self.shell.progress
        self.status = self.shell.status
        self.restore_button = self.shell.restore_button
        self.restore_button.clicked.connect(self._restore)
        self.shell.logs_button.clicked.connect(self._reveal_data)
        self.cancel_button = self.shell.cancel_button
        self.cancel_button.clicked.connect(self._cancel)
        self.import_button = self.shell.import_button
        self.import_button.clicked.connect(self._commit)
        self.library_table.itemSelectionChanged.connect(self._library_selection_changed)
        self.album_grid.itemSelectionChanged.connect(self._library_selection_changed)
        self.library_table.model().layoutChanged.connect(
            lambda: self._filter_library(self.library_search.text())
        )
        self.setStyleSheet(STYLE)
        self._find_action = QAction(self)
        self._find_action.setShortcut(QKeySequence.StandardKey.Find)
        self._find_action.triggered.connect(self.library_search.setFocus)
        self.addAction(self._find_action)
        self._open_action = QAction(self)
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)
        self._open_action.triggered.connect(self._choose_files)
        self.addAction(self._open_action)
        self._remove_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Backspace), self.table
        )
        self._remove_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._remove_shortcut.activated.connect(self._remove)
        self._compact = False
        self.sidebar.setCurrentRow(0)
        self._show_cover(None)
        self._set_status("Ready")
        self._sync_language_actions()
        self._retranslate_ui()
        self._library_selection_changed()

    def _workspace_changed(self, index: int) -> None:
        self.sidebar.blockSignals(True)
        self.sidebar.setCurrentRow(index)
        self.sidebar.blockSignals(False)
        self.heading_title.setText(
            tr(("iPod Library", "To Import", "Recovery & History")[index])
        )
        self.library_controls_action.setVisible(index == 0)
        self.inspector_button.setEnabled(index != 2)
        self._set_inspector_visible(self.inspector_button.isChecked())
        if index < 2:
            self.inspector_stack.setCurrentIndex(index)
        self.import_button.setVisible(index == 1)
        self._find_action.setEnabled(index == 0)

    def _set_inspector_visible(self, visible: bool) -> None:
        self.inspector_stack.setVisible(visible and self.pages.currentIndex() != 2)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "inspector_button"):
            compact = self.width() < 1080
            if compact != self._compact:
                self._compact = compact
                self.inspector_button.setChecked(not compact)

    def _library_selection_changed(self) -> None:
        if self.album_mode_button.isChecked():
            items = self.album_grid.selectedItems()
            item = items[0] if items else None
            album = (
                item.data(ALBUM_ROLE)
                if item is not None and not item.isHidden()
                else None
            )
            self._inspector_artwork_id = 0
            if isinstance(album, AlbumSummary):
                self.library_inspector_title.setText(album.title or tr("Unknown album"))
                self.library_inspector_details.setText(
                    "\n".join((album.artist, song_count(album.track_count)))
                )
                self._inspector_artwork_id = album.artwork_id
            else:
                self.library_inspector_title.setText(tr("No track selected"))
                self.library_inspector_details.clear()
            self._update_library_inspector_cover()
            return
        rows = [
            item.row()
            for item in self.library_table.selectionModel().selectedRows()
            if not self.library_table.isRowHidden(item.row())
        ]
        self._inspector_artwork_id = 0
        details = ""
        track = self.library_view.track_at(rows[0]) if len(rows) == 1 else None
        if track is not None:
            title = track.title
            duration = f"{max(0, track.length_ms) // 60000}:{max(0, track.length_ms) // 1000 % 60:02d}"
            details = "\n".join((track.artist, track.album, duration))
            self._inspector_artwork_id = track.artwork_id
        elif rows:
            title = tr("{count} selected").format(count=song_count(len(rows)))
        else:
            title = tr("No track selected")
        self.library_inspector_title.setText(title)
        self.library_inspector_details.setText(details)
        self._update_library_inspector_cover()

    def _update_library_inspector_cover(self) -> None:
        cover = self.library_view.inspector_cover
        pixmap = self._album_artwork.get(self._inspector_artwork_id)
        if pixmap is None:
            cover.setPixmap(
                glyph_icon(
                    "album",
                    100,
                    self.palette().color(QPalette.ColorRole.PlaceholderText),
                ).pixmap(QSize(100, 100))
            )
            self._request_artwork(self._inspector_artwork_id)
        else:
            cover.setPixmap(
                pixmap.scaled(
                    238,
                    238,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.PaletteChange,
        ) and hasattr(self, "import_button"):
            self._retint_glyph_icons()
            self._selection_changed()
            self._update_library_inspector_cover()
            if (
                self._open_album_summary is not None
                and self._open_album_summary.artwork_id not in self._album_artwork
            ):
                self.album_detail_cover.setPixmap(self._album_placeholder())
            self.album_grid.viewport().update()

    def _retint_glyph_icons(self) -> None:
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        for widget in self.findChildren(QAbstractButton):
            glyph = widget.property("classicDropGlyph")
            size = widget.property("classicDropGlyphSize")
            if isinstance(glyph, str) and isinstance(size, int):
                widget.setIcon(glyph_icon(glyph, size, color))

    def _submit(self, command: str, payload: object = None) -> None:
        if self._busy or self.worker is None:
            return
        self.worker.cancelled.clear()
        self.set_busy(True)
        self._current_progress = None
        self._set_status(
            {
                "discover": "Finding devices",
                "select": "Reading library",
                "preview": "Inspecting music",
                "commit": "Preparing import",
                "restore": "Restoring previous library",
                "eject": "Ejecting device",
            }.get(command, "Working")
        )
        self.request.emit(command, payload)

    def _set_status(self, template: str, **parameters: str) -> None:
        self._status_message = source_text(template, **parameters)
        self.status.setText(render_text(self._status_message))

    def _language_changed(self, _language: str) -> None:
        self._sync_language_actions()
        self._retranslate_ui()

    def _sync_language_actions(self) -> None:
        for language, action in self.language_actions.items():
            action.setChecked(
                self._language_manager.follows_system
                if language == SYSTEM_LANGUAGE
                else not self._language_manager.follows_system
                and language == self._language_manager.language
            )

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(tr("Classic Drop"))
        self._workspace_changed(self.pages.currentIndex())
        self.settings_button.setToolTip(tr("More"))
        self.settings_button.setAccessibleName(tr("More"))
        self.backups_action.setText(tr("Show backups and logs"))
        self.about_action.setText(tr("About Classic Drop"))
        self.settings_button.setToolTip(tr("Settings"))
        self.settings_button.setAccessibleName(tr("Settings"))
        self.settings_menu.setTitle(tr("Settings"))
        self.general_menu.setTitle(tr("General"))
        self.language_menu.setTitle(tr("Language"))
        self.language_actions[SYSTEM_LANGUAGE].setText(tr("Follow system"))
        if self.devices.count():
            self.devices.setItemText(0, tr(self._device_placeholder))
        for widget, label in (
            (self.refresh_button, "Refresh devices"),
            (self.eject_button, "Safely eject"),
            (self.remove_button, "Remove from queue"),
            (self.clear_cover_button, "Remove cover"),
        ):
            widget.setToolTip(tr(label))
            widget.setAccessibleName(tr(label))
        self._update_device_info()
        self.library_search.setPlaceholderText(tr("Search title, artist, or album"))
        self.library_search.setAccessibleName(tr("Search title, artist, or album"))
        self.library_table.setAccessibleName(tr("iPod Library"))
        self.table.setAccessibleName(tr("To Import"))
        self.list_mode_button.setText(tr("List"))
        self.album_mode_button.setText(tr("Albums"))
        library_headers = [
            "Title",
            "Artist",
            "Album",
            "Album artist",
            "Disc",
            "Track",
            "Duration",
        ]
        self.library_table.setHorizontalHeaderLabels(
            [tr(header) for header in library_headers]
        )
        for column, action in self.library_view.column_actions.items():
            action.setText(tr(library_headers[column]))
        self.back_button.setText(tr("Back to albums"))
        self.album_track_table.setHorizontalHeaderLabels(
            [tr(header) for header in ("Track", "Title", "Artist", "Duration")]
        )
        self.shell.retranslate()
        self.files_button.setText(tr("Add files"))
        self.folder_button.setText(tr("Add folder"))
        self.cover_button.setText(tr("Choose cover"))
        self.restore_button.setText(tr("Restore last import"))
        self.cancel_button.setText(tr("Cancel"))
        self.table.setHorizontalHeaderLabels(
            [
                "",
                tr("Title"),
                tr("Artist"),
                tr("Album"),
                tr("Album artist"),
                tr("Disc"),
                tr("Track"),
                tr("Status"),
            ]
        )
        self._queue_changed()
        for row, entry in enumerate(self._entries):
            item = self.table.item(row, 7)
            if item is not None:
                label = (
                    "Import after conversion"
                    if entry.status == "new" and entry.mode == "convert"
                    else STATUS[entry.status]
                )
                item.setText(tr(label))
                item.setToolTip(render_text(entry.detail) or entry.path.as_posix())
        self.library_count.setText(song_count(len(self._library_tracks)))
        if self._active is not None:
            self._update_device_info()
        if self._open_album_summary is not None:
            self._update_album_detail(self._open_album_summary)
        self._selection_changed()
        self.album_grid.viewport().update()
        self.status.setText(render_text(self._status_message))
        self.queue_empty_title.setText(tr("Import queue is empty"))
        self.queue_empty_detail.setText(
            tr("Add files or a folder to prepare an import.")
        )
        self._update_library_empty_state()
        self.shell.update_recovery(self._can_restore)
        self.quit_action.setText(tr("Quit Classic Drop"))
        self._library_selection_changed()

    def _update_album_detail(self, album: AlbumSummary) -> None:
        self.album_detail_title.setText(album.title or tr("Unknown album"))
        meta = album.artist or tr("Unknown artist")
        if album.year:
            meta += f"  ·  {album.year}"
        duration = f"{album.duration_ms // 60000}:{album.duration_ms // 1000 % 60:02d}"
        meta += f"\n{song_count(album.track_count)}  ·  {duration}"
        self.album_detail_meta.setText(meta)

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
        self._open_action.setEnabled(active and not busy)
        self.shell.update_recovery(self._can_restore)
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
                values[-1] = tr("Import after conversion")
            else:
                values[-1] = tr(STATUS[entry.status])
            for col, text in enumerate(values, 1):
                item = QTableWidgetItem(text)
                if col == 7 or entry.status == "error":
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    )
                item.setToolTip(entry.detail if col == 7 else text)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self.queue_stack.setCurrentWidget(
            self.table if entries else self.queue_empty_page
        )
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
        library_changed = (
            tracks != self._library_tracks or device_id != previous_device_id
        )
        if library_changed:
            self._album_artwork.clear()
            self._artwork_requests.clear()
            self.album_detail_stack.setCurrentWidget(self.album_grid)
            self._open_album_summary = None
        self._library_device_id = device_id
        self._library_tracks = tracks
        self.library_table.blockSignals(True)
        sorting = self.library_table.isSortingEnabled()
        self.library_table.setSortingEnabled(False)
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
                item = LibraryCell(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setData(Qt.ItemDataRole.UserRole, track)
                numeric = {
                    4: track.metadata.disc_number or 0,
                    5: track.track_number or 0,
                    6: seconds,
                }
                if column in numeric:
                    item.setData(Qt.ItemDataRole.UserRole + 1, numeric[column])
                self.library_table.setItem(row, column, item)
        self.library_table.setSortingEnabled(sorting)
        self.library_table.blockSignals(False)
        self.library_count.setText(song_count(len(tracks)))
        if library_changed:
            self._albums = group_albums(tracks)
            self._update_album_grid()
        self._filter_library(self.library_search.text())

    def _set_library_mode(self, mode: str) -> None:
        album_mode = mode == "album"
        self.list_mode_button.setChecked(not album_mode)
        self.album_mode_button.setChecked(album_mode)
        self._restore_library_page(album_mode)
        self.album_detail_stack.setCurrentWidget(self.album_grid)
        self._open_album_summary = None
        self._filter_library(self.library_search.text())

    def _update_library_empty_state(self) -> None:
        if not self._library_tracks:
            if self._active is None:
                title = "No iPod connected"
                detail = "Connect an iPod Classic to view its Library."
            else:
                title = "No music on this iPod"
                detail = "The selected iPod Library contains no tracks."
        elif self.library_search.text().strip():
            album_mode = self.album_mode_button.isChecked()
            if (
                album_mode
                and self.library_stack.currentWidget() is self.library_album_page
                and self.album_detail_stack.currentWidget() is self.album_detail_page
            ):
                return
            visible = (
                any(
                    not self.album_grid.item(row).isHidden()
                    for row in range(self.album_grid.count())
                )
                if album_mode
                else any(
                    not self.library_table.isRowHidden(row)
                    for row in range(self.library_table.rowCount())
                )
            )
            if not visible:
                title = "No matching music"
                detail = "Try another title, artist, or album."
            else:
                self._restore_library_page(album_mode)
                return
        else:
            if self.library_stack.currentWidget() is self.library_empty_page:
                self._restore_library_page(self.album_mode_button.isChecked())
            return

        self.library_empty_title.setText(tr(title))
        self.library_empty_detail.setText(tr(detail))
        self.library_stack.setCurrentWidget(self.library_empty_page)

    def _restore_library_page(self, album_mode: bool) -> None:
        self.library_stack.setCurrentWidget(
            self.library_album_page if album_mode else self.library_list_page
        )

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
        self._update_album_detail(album)
        pixmap = self._album_artwork.get(album.artwork_id)
        if pixmap is None:
            self.album_detail_cover.setPixmap(self._album_placeholder())
            self._request_artwork(album.artwork_id)
        else:
            self.album_detail_cover.setPixmap(
                pixmap.scaled(
                    230,
                    230,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
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
        self._library_selection_changed()

    def _album_placeholder(self) -> QPixmap:
        return glyph_icon(
            "album", 120, self.palette().color(QPalette.ColorRole.PlaceholderText)
        ).pixmap(QSize(120, 120))

    def _request_artwork(self, artwork_id: int) -> None:
        if (
            artwork_id <= 0
            or artwork_id in self._artwork_requests
            or self.worker is None
        ):
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
        if artwork.artwork_id == self._inspector_artwork_id:
            self._update_library_inspector_cover()
        for row in range(self.album_grid.count()):
            item = self.album_grid.item(row)
            album = item.data(ALBUM_ROLE)
            if (
                isinstance(album, AlbumSummary)
                and album.artwork_id == artwork.artwork_id
            ):
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
        for row in range(self.library_table.rowCount()):
            track = self.library_view.track_at(row)
            if track is None:
                continue
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
                    *(
                        value
                        for track in album.tracks
                        for value in (track.title, track.artist)
                    ),
                )
            ).casefold()
            self.album_grid.item(row).setHidden(bool(query and query not in haystack))
        self._update_library_empty_state()
        self._library_selection_changed()

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
        self.count_label.setText(
            f"{song_count(count)} / {song_count(len(self._entries))}"
        )
        self.import_button.setText(
            tr("Import {count}").format(count=song_count(count))
            if count
            else tr("Import selected")
        )
        self.import_button.setEnabled(
            self._active is not None and count > 0 and not self._busy
        )

    def _show_cover(self, artwork: ArtworkPixels | None) -> None:
        if artwork is None:
            self.cover.setPixmap(
                glyph_icon(
                    "album",
                    64,
                    self.palette().color(QPalette.ColorRole.PlaceholderText),
                ).pixmap(QSize(64, 64))
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
            self.track_title.setText(tr("No track selected"))
            self.track_details.clear()
            self.source_label.clear()
            return
        entry = self._entries[row]
        self._show_cover(entry.artwork)
        self.track_title.setText(entry.title or entry.path.stem)
        seconds = entry.length_ms // 1000
        self.track_details.setText(
            tr("{artist}\n{album}\n\n{duration}  ·  {size}\n{status}").format(
                artist=entry.artist,
                album=entry.album,
                duration=f"{seconds // 60}:{seconds % 60:02d}",
                size=readable_size(entry.size_bytes),
                status=tr(STATUS[entry.status]),
            )
        )
        self.source_label.setText(str(entry.path))
        self.source_label.setToolTip(entry.detail or str(entry.path))

    def _choose_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            tr("Select music"),
            "",
            tr(
                "Music (*.mp3 *.m4a *.flac *.wav *.aif *.aiff *.aac *.ogg *.opus *.wma *.ape *.wv);;All files (*)"
            ),
        )
        if paths:
            self._add_paths(tuple(Path(p) for p in paths))

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, tr("Select an album or music folder")
        )
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
            self,
            tr("Select album artwork"),
            "",
            tr("Images (*.jpg *.jpeg *.png *.webp)"),
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
            QMessageBox.warning(self, tr("Invalid track number"), str(error))

    def _restore(self) -> None:
        if (
            QMessageBox.question(
                self,
                tr("Restore last import"),
                tr(
                    "Restore the library to its state before the last import and remove tracks added by it?"
                ),
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._submit("restore")

    def _cancel(self) -> None:
        if self.worker:
            self.worker.cancelled.set()
        self._set_status("Canceling; waiting for the current step to finish")
        self.cancel_button.setEnabled(False)

    def _succeeded(self, command: str, reply: Reply) -> None:
        if self._closing:
            self.request.emit("close", None)
            return
        if command == "artwork":
            self._show_album_artwork(cast("ArtworkImage | None", reply.value))
            return
        self._current_progress = None
        previous_active = self._active
        self._active, self._can_restore = reply.active, reply.can_restore
        self.set_busy(False)
        if command == "discover":
            candidates = cast("tuple[DeviceCandidate, ...]", reply.value)
            self.devices.blockSignals(True)
            self.devices.clear()
            self._device_placeholder = (
                "Choose iPod Classic" if candidates else "No iPod Classic connected"
            )
            self.devices.addItem(tr(self._device_placeholder), None)
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
            self._set_status("Found {count} devices", count=str(len(candidates)))
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
            self.pages.setCurrentWidget(self.library_page)
            self._set_status("Library loaded")
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
            self.pages.setCurrentWidget(self.import_page)
            self._set_status(
                "Preview ready"
                if self._entries
                else "No supported music files in the selected locations"
            )
        elif command == "cover":
            artwork = cast("ArtworkPixels", reply.value)
            self.show_entries(
                tuple(
                    replace(e, artwork=artwork) if e.token in self._cover_tokens else e
                    for e in self.edited_entries()
                )
            )
            self._set_status("Cover updated")
        elif command == "commit":
            result = cast("ImportResult", reply.value)
            self._paths = ()
            self.show_entries(())
            self._update_library_table()
            self._set_status("Imported {count}", count=song_count(result.added))
            if result.warnings:
                QMessageBox.warning(
                    self,
                    tr("Import completed with warnings"),
                    "\n".join(result.warnings),
                )
        elif command == "restore":
            self._paths = ()
            self.show_entries(())
            self._update_library_table()
            self._set_status("Restore complete")
        elif command == "eject":
            self._paths = ()
            self.show_entries(())
            self._update_library_table()
            self.devices.blockSignals(True)
            self.devices.clear()
            self._device_placeholder = "Device ejected"
            self.devices.addItem(tr(self._device_placeholder), None)
            self.devices.blockSignals(False)
            self._set_status("You can disconnect the iPod")
        self._update_device_info()
        self.set_busy(self._busy)

    def _failed(self, command: str, message: object, reply: Reply) -> None:
        if self._closing:
            self.request.emit("close", None)
            return
        if command == "artwork":
            return
        display_message = (
            render_text(message) if isinstance(message, str) else str(message)
        )
        self._active, self._can_restore = reply.active, reply.can_restore
        self._update_library_table()
        self.set_busy(False)
        canceled = (
            (isinstance(message, SourceText) and message.source == "Operation canceled")
            or "cancel" in display_message.casefold()
            or "取消" in display_message
        )
        self._set_status("Operation canceled" if canceled else "Operation incomplete")
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("Classic Drop"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(display_message[:400])
        if len(display_message) > 400:
            dialog.setDetailedText(display_message)
        if not canceled:
            dialog.exec()
        self._update_device_info()

    def _update_device_info(self) -> None:
        if self._active:
            active = self._active
            self.device_info.setText(
                tr("{model}  ·  {number}  ·  {count}  ·  {size} available").format(
                    model=active.profile.display_name,
                    number=active.profile.model_number,
                    count=song_count(len(active.library.tracks)),
                    size=readable_size(active.candidate.available_bytes),
                )
            )
        else:
            self.device_info.setText(tr("No device connected"))

    def _progress(self, progress: WriteProgress) -> None:
        if self._closing:
            return
        self._current_progress = progress
        phase = progress.phase
        message = "Writing and verifying: {item}"
        if phase == "inspect":
            message = "Inspecting music: {item}"
        elif phase == "history":
            message = "Keeping playback history: {item}"
        elif phase.startswith("database."):
            message = "Preparing library and artwork: {item}"
        elif "recover" in phase:
            message = "Restoring library: {item}"
        self._set_status(message, item=progress.current_item)
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
            tr("About Classic Drop"),
            tr(
                "Classic Drop 0.1.0\n\niPod Classic music importer\nBased on iOpenPod 2.0.15\nGPL-3.0-or-later\n\nSee CLASSIC_DROP.md for source and third-party license notices."
            ),
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
