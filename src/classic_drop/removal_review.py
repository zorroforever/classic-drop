"""Final confirmation of one prepared, recoverable Music Track removal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from classic_drop.i18n import tr

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent

    from classic_drop.engine import RemovalReview
    from classic_drop.removal_view import RemovalPackageEntry


class RemovalReviewDialog(QDialog):
    def __init__(
        self,
        review: RemovalReview,
        entries: tuple[RemovalPackageEntry, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(760, 520)
        count = QLocale().toString(len(review.track_ids))
        title = tr("Remove {count} songs from the iPod Library?").format(count=count)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.scope_label = QLabel(
            tr(
                "These songs will be removed from the entire Library and all Playlists. Original music files remain on the iPod for recovery; device space will not be freed immediately."
            )
        )
        self.scope_label.setWordWrap(True)
        layout.addWidget(self.scope_label)
        size = tr("Unique media retained for recovery: {size}").format(
            size=QLocale().formattedDataSize(review.size_bytes)
        )
        layout.addWidget(QLabel(size))
        selected_ids = set(review.track_ids)
        affected = tuple(
            playlist.name
            for playlist in review.source.library.playlists
            if any(entry.track_id in selected_ids for entry in playlist.entries)
        )
        playlists = QLabel(
            tr("Affected playlists: {count}").format(
                count=QLocale().toString(len(affected))
            )
        )
        layout.addWidget(playlists)
        self.playlist_list = QListWidget()
        self.playlist_list.addItems(affected)
        self.playlist_list.setAccessibleName(tr("Playlist"))
        self.playlist_list.setMaximumHeight(90)
        self.playlist_list.setVisible(bool(affected))
        layout.addWidget(self.playlist_list)
        self.table = QTableWidget(len(entries), 4)
        self.table.setHorizontalHeaderLabels(
            [tr(label) for label in ("Title", "Artist", "Album", "Added by filter")]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAccessibleName(tr("Review music removal"))
        for row, entry in enumerate(entries):
            for column, value in enumerate(
                (
                    entry.track.title,
                    entry.track.artist,
                    entry.track.album,
                    entry.source_filter,
                )
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox()
        self.cancel_button = buttons.addButton(
            tr("Cancel"), QDialogButtonBox.ButtonRole.RejectRole
        )
        self.remove_button = buttons.addButton(
            tr("Recoverably remove {count} songs").format(count=count),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.remove_button.setAutoDefault(False)
        self.remove_button.setDefault(False)
        self.remove_button.setStyleSheet("color: #C00000; font-weight: 600;")
        self.cancel_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.reject()
        else:
            super().keyPressEvent(event)
