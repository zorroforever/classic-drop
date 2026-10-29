"""Read-only Library views and their native toolbar controls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from classic_drop.albums import CARD_SIZE, AlbumCardDelegate
from classic_drop.presentation import button, empty_state
from iPodDB.library import Track

if TYPE_CHECKING:
    from classic_drop.window import MainWindow


class AlbumGrid(QListWidget):
    """Distribute fixed-width album cards evenly across the available row."""

    LAYOUT_GUTTER = 20

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.update_columns()
        super().resizeEvent(event)

    def update_columns(self) -> None:
        width = self.viewport().width()
        visible = sum(not self.item(i).isHidden() for i in range(self.count()))
        content_width = max(1, width - self.LAYOUT_GUTTER)
        columns = max(
            1,
            min(max(1, visible), content_width // (CARD_SIZE.width() + 20)),
        )
        cell_width = max(CARD_SIZE.width() + 20, content_width // columns)
        size = QSize(cell_width, CARD_SIZE.height() + 20)
        if size != self.gridSize():
            self.setGridSize(size)


class LibraryCell(QTableWidgetItem):
    """Keep numeric ordering separate from localized display text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(Qt.ItemDataRole.UserRole + 1)
        right = other.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(left, int) and isinstance(right, int):
            return left < right
        return self.text().casefold() < other.text().casefold()


class LibraryView(QWidget):
    def __init__(self, controller: MainWindow) -> None:
        super().__init__()
        library_layout = QVBoxLayout(self)
        library_toolbar = QHBoxLayout()
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText("Search title, artist, or album")
        self.library_search.textChanged.connect(controller._filter_library)
        library_toolbar.addWidget(self.library_search, 1)
        self.library_count = QLabel("0 songs")
        self.library_count.setObjectName("muted")
        library_toolbar.addWidget(self.library_count)
        self.delete_button = button("Add selection to removal package", "plus")
        self.delete_button.clicked.connect(controller._add_library_selection_to_package)
        self.delete_button.setEnabled(False)
        library_toolbar.addWidget(self.delete_button)
        self.controls = QWidget()
        self.controls.setLayout(library_toolbar)
        library_toolbar.setContentsMargins(0, 0, 0, 0)
        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        self.list_mode_button = QToolButton()
        self.list_mode_button.setText("List")
        self.list_mode_button.setCheckable(True)
        self.album_mode_button = QToolButton()
        self.album_mode_button.setText("Albums")
        self.album_mode_button.setCheckable(True)
        mode_group.addButton(self.list_mode_button)
        mode_group.addButton(self.album_mode_button)
        self.list_mode_button.setChecked(True)
        self.list_mode_button.clicked.connect(
            lambda: controller._set_library_mode("list")
        )
        self.album_mode_button.clicked.connect(
            lambda: controller._set_library_mode("album")
        )
        library_toolbar.insertWidget(0, self.list_mode_button)
        library_toolbar.insertWidget(1, self.album_mode_button)
        self.library_table = QTableWidget(0, 7)
        self.library_table.setHorizontalHeaderLabels(
            ["Title", "Artist", "Album", "Album artist", "Disc", "Track", "Duration"]
        )
        self.library_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.library_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.library_table.setAlternatingRowColors(True)
        self.library_table.setShowGrid(False)
        self.library_table.setWordWrap(False)
        self.library_table.verticalHeader().hide()
        for column, width in enumerate((190, 130, 180, 130, 45, 45, 70)):
            self.library_table.setColumnWidth(column, width)
        self.library_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.library_table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.column_menu = QMenu(self.library_table)
        self.column_actions = {}
        for column in range(7):
            action = self.column_menu.addAction("")
            action.setCheckable(True)
            action.setChecked(column not in (3, 4, 5))
            action.setEnabled(column != 0)
            self.library_table.setColumnHidden(column, not action.isChecked())
            action.toggled.connect(
                lambda checked, selected=column: self.library_table.setColumnHidden(
                    selected, not checked
                )
            )
            self.column_actions[column] = action
        header = self.library_table.horizontalHeader()
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.library_table.setSortingEnabled(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(
            lambda position: self.column_menu.exec(header.mapToGlobal(position))
        )
        self.library_stack = QStackedWidget()
        list_page = QWidget()
        self.library_list_page = list_page
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(self.library_table)
        self.library_stack.addWidget(list_page)
        album_page = QWidget()
        self.library_album_page = album_page
        album_layout = QVBoxLayout(album_page)
        album_layout.setContentsMargins(0, 0, 0, 0)
        self.album_detail_stack = QStackedWidget()
        self.album_grid = AlbumGrid()
        self.album_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.album_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.album_grid.setMovement(QListWidget.Movement.Static)
        self.album_grid.setSpacing(0)
        self.album_grid.setViewportMargins(AlbumGrid.LAYOUT_GUTTER, 0, 0, 0)
        self.album_grid.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.album_grid.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.album_grid.setUniformItemSizes(True)
        self.album_grid.setItemDelegate(
            AlbumCardDelegate(controller._request_artwork, self.album_grid)
        )
        self.album_grid.itemDoubleClicked.connect(controller._open_album)
        self.album_detail_stack.addWidget(self.album_grid)
        self.album_detail_page = QWidget()
        album_detail_row = QHBoxLayout(self.album_detail_page)
        album_detail_row.setContentsMargins(8, 8, 8, 8)
        detail_left = QVBoxLayout()
        self.back_button = button("Back to albums", "skip-back")
        self.back_button.clicked.connect(
            lambda: self.album_detail_stack.setCurrentWidget(self.album_grid)
        )
        detail_left.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignLeft)
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
        self.album_track_table.setHorizontalHeaderLabels(
            ["Track", "Title", "Artist", "Duration"]
        )
        self.album_track_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.album_track_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.album_track_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.album_track_table.setAlternatingRowColors(True)
        self.album_track_table.setShowGrid(False)
        self.album_track_table.verticalHeader().hide()
        self.album_track_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        album_detail_row.addWidget(self.album_track_table, 1)
        self.album_detail_stack.addWidget(self.album_detail_page)
        album_layout.addWidget(self.album_detail_stack)
        self.library_stack.addWidget(album_page)
        (
            self.library_empty_page,
            self.library_empty_title,
            self.library_empty_detail,
        ) = empty_state()
        self.library_stack.addWidget(self.library_empty_page)
        library_layout.addWidget(self.library_stack, 1)
        library_layout.setContentsMargins(0, 0, 0, 0)
        self.library_table.verticalHeader().setDefaultSectionSize(34)
        self.library_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.inspector = QWidget()
        inspector_layout = QVBoxLayout(self.inspector)
        inspector_layout.setContentsMargins(16, 16, 16, 16)
        self.inspector_cover = QLabel()
        self.inspector_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.inspector_cover.setFixedSize(240, 240)
        self.inspector_cover.setObjectName("cover")
        inspector_layout.addWidget(
            self.inspector_cover, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self.inspector_title = QLabel()
        self.inspector_title.setWordWrap(True)
        font = QFont()
        font.setPointSize(14)
        font.setWeight(QFont.Weight.DemiBold)
        self.inspector_title.setFont(font)
        inspector_layout.addWidget(self.inspector_title)
        self.inspector_details = QLabel()
        self.inspector_details.setWordWrap(True)
        self.inspector_details.setObjectName("muted")
        self.inspector_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        inspector_layout.addWidget(self.inspector_details)
        inspector_layout.addStretch()

    def track_at(self, row: int) -> Track | None:
        item = self.library_table.item(row, 0)
        track = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return track if isinstance(track, Track) else None
