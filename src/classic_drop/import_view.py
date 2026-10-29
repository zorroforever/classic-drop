"""Editable import queue, source artwork inspector and bounded number editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from classic_drop.presentation import button, empty_state, tool

if TYPE_CHECKING:
    from classic_drop.window import MainWindow


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


class ImportView(QWidget):
    def __init__(self, controller: MainWindow) -> None:
        super().__init__()
        import_layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.files_button = button("Add files", "plus")
        self.files_button.clicked.connect(controller._choose_files)
        self.folder_button = button("Add folder", "folder")
        self.folder_button.clicked.connect(controller._choose_folder)
        self.remove_button = tool("Remove from queue", "minus")
        self.remove_button.clicked.connect(controller._remove)
        toolbar.addWidget(self.files_button)
        toolbar.addWidget(self.folder_button)
        toolbar.addWidget(self.remove_button)
        toolbar.addStretch()
        self.count_label = QLabel("0 songs")
        self.count_label.setObjectName("muted")
        toolbar.addWidget(self.count_label)
        self.status_filter = QComboBox()
        for label, status in (
            ("All statuses", "all"),
            ("New", "new"),
            ("Confirmed duplicate", "confirmed_duplicate"),
            ("History match", "history_match"),
            ("Possible duplicate", "possible_duplicate"),
            ("Check incomplete", "check_incomplete"),
            ("Cannot import", "error"),
        ):
            self.status_filter.addItem(label, status)
        self.status_filter.currentIndexChanged.connect(controller._filter_import_status)
        toolbar.addWidget(self.status_filter)
        import_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["", "Title", "Artist", "Album", "Album artist", "Disc", "Track", "Status"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.horizontalHeader().setMinimumSectionSize(34)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for column, width in enumerate((34, 175, 110, 140, 110, 40, 40, 105)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setItemDelegateForColumn(5, NumberDelegate(self.table))
        self.table.setItemDelegateForColumn(6, NumberDelegate(self.table))
        self.table.itemSelectionChanged.connect(controller._selection_changed)
        self.table.itemChanged.connect(controller._queue_changed)
        self.queue_stack = QStackedWidget()
        self.queue_stack.addWidget(self.table)
        (
            self.queue_empty_page,
            self.queue_empty_title,
            self.queue_empty_detail,
        ) = empty_state()
        self.queue_stack.addWidget(self.queue_empty_page)
        self.queue_stack.setCurrentWidget(self.queue_empty_page)
        splitter.addWidget(self.queue_stack)
        details = QWidget()
        self.queue_details = details
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setFixedSize(200, 200)
        self.cover.setObjectName("cover")
        detail_layout.addWidget(self.cover)
        cover_actions = QHBoxLayout()
        self.cover_button = button("Choose cover", "photo")
        self.cover_button.clicked.connect(controller._choose_cover)
        cover_actions.addWidget(self.cover_button)
        self.clear_cover_button = tool("Remove cover", "x")
        self.clear_cover_button.clicked.connect(controller._clear_cover)
        cover_actions.addWidget(self.clear_cover_button)
        cover_actions.addStretch()
        detail_layout.addLayout(cover_actions)
        self.track_title = QLabel("No track selected")
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
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([850, 230])
        import_layout.addWidget(splitter, 1)
        import_layout.setContentsMargins(0, 0, 0, 0)
        self.table.verticalHeader().setDefaultSectionSize(34)
