"""Multi-dimension music filtering and the in-memory removal package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from classic_drop.i18n import song_count, tr
from classic_drop.presentation import button
from classic_drop.removal import RemovalFilters, filter_music
from iOpenPod.GUI.widgets.checkable_combo_box import CheckableComboBox
from iPodDB.library import LibrarySnapshot, Track

if TYPE_CHECKING:
    from classic_drop.window import MainWindow


class FilterComboBox(CheckableComboBox):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        self._empty_label = label
        super().__init__(parent)

    def selection_text(self) -> str:
        selected = tuple(
            self.item(index).text()
            for index in range(self.count())
            if self.item(index).isEnabled()
            and self.item(index).checkState() == Qt.CheckState.Checked
        )
        if not selected:
            return tr(self._empty_label)
        return (
            selected[0]
            if len(selected) == 1
            else tr("{count} selected").format(count=song_count(len(selected)))
        )


@dataclass(frozen=True, slots=True)
class RemovalPackageEntry:
    track: Track
    source_filter: str


class RemovalView(QWidget):
    packageChanged = Signal()

    def __init__(self, controller: MainWindow) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        filters_row = QHBoxLayout()
        self.title_filter = self._text_filter("Title")
        self.artist_filter = self._text_filter("Artist")
        self.album_filter = self._text_filter("Album")
        for field in (self.title_filter, self.artist_filter, self.album_filter):
            filters_row.addWidget(field, 1)
        layout.addLayout(filters_row)
        facets = QHBoxLayout()
        self.genre_filter = FilterComboBox("Any genre")
        self.year_filter = FilterComboBox("Any year")
        self.playlist_filter = FilterComboBox("Any Playlist")
        for combo in (self.genre_filter, self.year_filter, self.playlist_filter):
            facets.addWidget(combo, 1)
            combo.model().dataChanged.connect(self._refresh_results)
        layout.addLayout(facets)
        for field in (self.title_filter, self.artist_filter, self.album_filter):
            field.textChanged.connect(self._refresh_results)

        self.match_count = QLabel("0 songs")
        self.match_count.setObjectName("muted")
        controls = QHBoxLayout()
        controls.addWidget(self.match_count, 1)
        self.add_selected_button = button("Add selected to package", "plus")
        self.add_selected_button.clicked.connect(controller._add_removal_selection)
        controls.addWidget(self.add_selected_button)
        self.add_matches_button = button("Add all matches", "playlist")
        self.add_matches_button.clicked.connect(controller._add_all_removal_matches)
        controls.addWidget(self.add_matches_button)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.results_table = self._table(
            ("Title", "Artist", "Album", "Genre", "Year", "Duration")
        )
        splitter.addWidget(self.results_table)

        package = QWidget()
        package_layout = QVBoxLayout(package)
        package_layout.setContentsMargins(0, 4, 0, 0)
        package_header = QHBoxLayout()
        self.package_count = QLabel("To remove: 0 songs")
        package_header.addWidget(self.package_count, 1)
        self.remove_selected_button = button("Remove selected from package", "minus")
        self.remove_selected_button.clicked.connect(self._remove_package_selection)
        package_header.addWidget(self.remove_selected_button)
        self.clear_package_button = button("Clear package", "x")
        self.clear_package_button.clicked.connect(self.clear_package)
        package_header.addWidget(self.clear_package_button)
        package_layout.addLayout(package_header)
        self.package_table = self._table(
            ("Title", "Artist", "Album", "Added by filter")
        )
        package_layout.addWidget(self.package_table, 1)
        splitter.addWidget(package)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        layout.setContentsMargins(0, 0, 0, 0)

        self._snapshot: LibrarySnapshot | None = None
        self._device_id: str | None = None
        self._source_revision: str | None = None
        self._tracks_by_id: dict[int, Track] = {}
        self._matches: tuple[Track, ...] = ()
        self._package: dict[int, RemovalPackageEntry] = {}
        self.results_table.itemSelectionChanged.connect(self._sync_controls)
        self.package_table.itemSelectionChanged.connect(self._sync_controls)
        self._sync_controls()

    @staticmethod
    def _text_filter(label: str) -> QLineEdit:
        field = QLineEdit()
        field.setPlaceholderText(tr(label))
        field.setClearButtonEnabled(True)
        return field

    @staticmethod
    def _table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels([tr(header) for header in headers])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @property
    def package_entries(self) -> tuple[RemovalPackageEntry, ...]:
        return tuple(self._package.values())

    @property
    def source_snapshot(self) -> LibrarySnapshot | None:
        return self._snapshot

    @property
    def source_revision(self) -> str | None:
        return self._source_revision

    def set_source(
        self,
        snapshot: LibrarySnapshot | None,
        device_id: str | None,
        source_revision: str | None = None,
    ) -> None:
        if (
            snapshot == self._snapshot
            and device_id == self._device_id
            and source_revision == self._source_revision
        ):
            return
        changed = self._snapshot is not None and (
            snapshot != self._snapshot
            or device_id != self._device_id
            or source_revision != self._source_revision
        )
        self._snapshot, self._device_id, self._source_revision = (
            snapshot,
            device_id,
            source_revision,
        )
        self._tracks_by_id = (
            {track.track_id: track for track in snapshot.tracks} if snapshot else {}
        )
        if changed:
            self._package.clear()
            self.packageChanged.emit()
        self._populate_facets()
        self._refresh_results()
        self._render_package()

    def _populate_facets(self) -> None:
        for combo in (self.genre_filter, self.year_filter, self.playlist_filter):
            combo.blockSignals(True)
            combo.clear()
        tracks = tuple(self._tracks_by_id.values())
        genres: dict[str | None, str] = {}
        for track in tracks:
            value = track.genre or None
            genres.setdefault(value.casefold() if value else None, value or "")
        for value in sorted(genres, key=lambda item: item or ""):
            label = tr("Missing genre") if value is None else genres[value]
            self.genre_filter.add_choice(label, value, checked=False, enabled=True)
        years: set[int | None] = {track.year or None for track in tracks}
        for year_value in sorted(years, key=lambda item: item or 0):
            label = tr("Missing year") if year_value is None else str(year_value)
            self.year_filter.add_choice(label, year_value, checked=False, enabled=True)
        playlists = getattr(self._snapshot, "playlists", ())
        for playlist in playlists:
            if playlist.entries:
                self.playlist_filter.add_choice(
                    playlist.name,
                    playlist.playlist_id,
                    checked=False,
                    enabled=True,
                )
        for combo in (self.genre_filter, self.year_filter, self.playlist_filter):
            combo.blockSignals(False)
            combo.refresh_summary()

    def filters(self) -> RemovalFilters:
        return RemovalFilters(
            title=self.title_filter.text(),
            artist=self.artist_filter.text(),
            album=self.album_filter.text(),
            genres=tuple(
                self.genre_filter.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(self.genre_filter.count())
                if self.genre_filter.item(index).checkState() == Qt.CheckState.Checked
            ),
            years=tuple(
                self.year_filter.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(self.year_filter.count())
                if self.year_filter.item(index).checkState() == Qt.CheckState.Checked
            ),
            playlists=tuple(
                self.playlist_filter.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(self.playlist_filter.count())
                if self.playlist_filter.item(index).checkState()
                == Qt.CheckState.Checked
            ),
        )

    def filter_description(self) -> str:
        filters = self.filters()
        values = []
        for label, value in (
            ("Title", filters.title),
            ("Artist", filters.artist),
            ("Album", filters.album),
        ):
            if value.strip():
                values.append(f"{tr(label)}: {value.strip()}")
        for label, selected in (
            ("Genre", filters.genres),
            ("Year", filters.years),
            ("Playlist", filters.playlists),
        ):
            if selected:
                values.append(f"{tr(label)}: {self._selected_labels(label)}")
        return "; ".join(values) or tr("Library selection")

    def _selected_labels(self, dimension: str) -> str:
        combo = {
            "Genre": self.genre_filter,
            "Year": self.year_filter,
            "Playlist": self.playlist_filter,
        }[dimension]
        return ", ".join(
            combo.item(index).text()
            for index in range(combo.count())
            if combo.item(index).checkState() == Qt.CheckState.Checked
        )

    def _refresh_results(self, *_args: object) -> None:
        self._matches = (
            filter_music(self._snapshot, self.filters())
            if self._snapshot is not None
            else ()
        )
        self.results_table.setRowCount(len(self._matches))
        for row, track in enumerate(self._matches):
            self._write_track_row(
                self.results_table,
                row,
                track,
                (
                    track.title,
                    track.artist,
                    track.album,
                    track.genre,
                    str(track.year or ""),
                    self._duration(track),
                ),
            )
        self.match_count.setText(
            tr("{count} matches").format(count=song_count(len(self._matches)))
        )
        self._sync_controls()

    def _write_track_row(
        self,
        table: QTableWidget,
        row: int,
        track: Track,
        values: tuple[str, ...],
    ) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, track.track_id)
            table.setItem(row, column, item)

    @staticmethod
    def _duration(track: Track) -> str:
        seconds = max(0, track.length_ms) // 1000
        return f"{seconds // 60}:{seconds % 60:02d}"

    def selected_match_ids(self) -> tuple[int, ...]:
        track_ids: list[int] = []
        for row in self.results_table.selectionModel().selectedRows():
            item = self.results_table.item(row.row(), 0)
            if item is None:
                continue
            track_id = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(track_id, int):
                track_ids.append(track_id)
        return tuple(track_ids)

    def matching_ids(self) -> tuple[int, ...]:
        return tuple(track.track_id for track in self._matches)

    def add_to_package(self, track_ids: tuple[int, ...], source_filter: str) -> int:
        added = 0
        for track_id in dict.fromkeys(track_ids):
            track = self._tracks_by_id.get(track_id)
            if track is None or track_id in self._package:
                continue
            self._package[track_id] = RemovalPackageEntry(track, source_filter)
            added += 1
        if added:
            self._render_package()
            self.packageChanged.emit()
        return added

    def clear_package(self) -> None:
        if self._package:
            self._package.clear()
            self._render_package()
            self.packageChanged.emit()

    def _remove_package_selection(self) -> None:
        ids = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.package_table.selectionModel().selectedRows()
            if self.package_table.item(item.row(), 0) is not None
        }
        if not ids:
            return
        self._package = {
            track_id: entry
            for track_id, entry in self._package.items()
            if track_id not in ids
        }
        self._render_package()
        self.packageChanged.emit()

    def _render_package(self) -> None:
        self.package_table.setRowCount(len(self._package))
        for row, entry in enumerate(self._package.values()):
            self._write_track_row(
                self.package_table,
                row,
                entry.track,
                (
                    entry.track.title,
                    entry.track.artist,
                    entry.track.album,
                    entry.source_filter,
                ),
            )
        self.package_count.setText(
            tr("To remove: {count} songs").format(count=song_count(len(self._package)))
        )
        self._sync_controls()

    def _sync_controls(self, *_args: object) -> None:
        self.add_selected_button.setEnabled(bool(self.selected_match_ids()))
        self.add_matches_button.setEnabled(bool(self._matches))
        self.remove_selected_button.setEnabled(
            bool(self.package_table.selectionModel().selectedRows())
        )
        self.clear_package_button.setEnabled(bool(self._package))

    def retranslate(self) -> None:
        for field, label in (
            (self.title_filter, "Title"),
            (self.artist_filter, "Artist"),
            (self.album_filter, "Album"),
        ):
            field.setPlaceholderText(tr(label))
        self.genre_filter._empty_label = "Any genre"
        self.year_filter._empty_label = "Any year"
        self.playlist_filter._empty_label = "Any Playlist"
        for index in range(self.genre_filter.count()):
            if self.genre_filter.item(index).data(Qt.ItemDataRole.UserRole) is None:
                self.genre_filter.item(index).setText(tr("Missing genre"))
        for index in range(self.year_filter.count()):
            if self.year_filter.item(index).data(Qt.ItemDataRole.UserRole) is None:
                self.year_filter.item(index).setText(tr("Missing year"))
        self.genre_filter.refresh_summary()
        self.year_filter.refresh_summary()
        self.playlist_filter.refresh_summary()
        self.add_selected_button.setText(tr("Add selected to package"))
        self.add_matches_button.setText(tr("Add all matches"))
        self.remove_selected_button.setText(tr("Remove selected from package"))
        self.clear_package_button.setText(tr("Clear package"))
        for table, headers in (
            (
                self.results_table,
                ("Title", "Artist", "Album", "Genre", "Year", "Duration"),
            ),
            (
                self.package_table,
                ("Title", "Artist", "Album", "Added by filter"),
            ),
        ):
            table.setHorizontalHeaderLabels([tr(header) for header in headers])
        self.match_count.setText(
            tr("{count} matches").format(count=song_count(len(self._matches)))
        )
        self._render_package()
