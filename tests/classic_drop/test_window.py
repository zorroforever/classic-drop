from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from classic_drop.engine import ImportResult, PreviewEntry
from classic_drop.i18n import song_count
from classic_drop.window import MainWindow
from classic_drop.worker import Reply
from iOpenPod.app.models.artwork import ArtworkImage
from iPodDB.library import LibrarySnapshot, Track, TrackMetadata
from iPodDB.library.playlists import Playlist, PlaylistEntry


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_no_device_state_disables_import(app):
    window = MainWindow(start_worker=False)
    assert not window.import_button.isEnabled()
    assert not window.files_button.isEnabled()
    assert "Classic Drop" in window.windowTitle()
    window.close()


def test_preview_keeps_duplicates_unchecked_and_tracks_edits(app):
    window = MainWindow(start_worker=False)
    entries = (
        PreviewEntry("one", Path("/tmp/one.mp3"), title="One", artist="Artist"),
        PreviewEntry(
            "two", Path("/tmp/two.mp3"), title="Two", selected=False, status="imported"
        ),
    )
    window.show_entries(entries)
    assert window.table.item(0, 0).checkState() == Qt.CheckState.Checked
    assert window.table.item(1, 0).checkState() == Qt.CheckState.Unchecked
    window.table.item(0, 1).setText("夜曲")
    assert window.edited_entries()[0].title == "夜曲"
    assert not window.edited_entries()[1].selected
    window.close()


def test_album_grid_centers_cards_when_resized_and_filtered(app):
    window = MainWindow(start_worker=False)
    tracks = tuple(
        Track(
            track_id=i + 1,
            title=f"Track {i}",
            artist="Artist",
            album=f"Album {i}",
            length_ms=60000,
        )
        for i in range(6)
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=tracks))
    window.resize(1400, 760)
    window.show()
    window._update_library_table()
    window._set_library_mode("album")
    app.processEvents()
    app.processEvents()

    grid = window.album_grid
    for width in (1400, 1050):
        window.resize(width, 760)
        app.processEvents()
        app.processEvents()
        first = grid.visualItemRect(grid.item(0))
        rightmost = first
        for row in range(1, grid.count()):
            rect = grid.visualItemRect(grid.item(row))
            if rect.y() != first.y():
                break
            rightmost = rect
        left_edge = grid.viewport().x() + first.left()
        right_edge = grid.width() - grid.viewport().x() - rightmost.right() - 1
        assert abs(left_edge - right_edge) <= 3
        assert first.width() == 190

    window.library_search.setText("Album 3")
    app.processEvents()
    app.processEvents()
    rect = grid.visualItemRect(grid.item(3))
    centered_x = grid.viewport().x() + rect.center().x()
    assert abs(centered_x - grid.rect().center().x()) <= 3
    window.close()


def test_duplicate_can_be_explicitly_selected_and_filtered(app):
    window = MainWindow(start_worker=False)
    window.show_entries(
        (
            PreviewEntry(
                "duplicate",
                Path("/tmp/copy.m4a"),
                title="Copy",
                status="confirmed_duplicate",
                selected=False,
                detail="SHA-256 matches queued file: original.m4a",
            ),
            PreviewEntry("new", Path("/tmp/new.m4a"), title="New"),
        )
    )

    duplicate_check = window.table.item(0, 0)
    duplicate_check.setCheckState(Qt.CheckState.Checked)
    window.import_view.status_filter.setCurrentIndex(
        window.import_view.status_filter.findData("confirmed_duplicate")
    )

    assert window.edited_entries()[0].selected
    assert not window.table.isRowHidden(0)
    assert window.table.isRowHidden(1)
    assert "SHA-256" in window.table.item(0, 7).toolTip()
    window.close()


def test_library_view_lists_existing_tracks_and_filters_without_editing(app):
    window = MainWindow(start_worker=False)
    tracks = (
        Track(
            track_id=1,
            title="Blue Train",
            artist="John Coltrane",
            album="Blue Train",
            length_ms=60000,
            track_number=1,
            metadata=TrackMetadata(disc_number=1),
        ),
        Track(
            track_id=2,
            title="Naima",
            artist="John Coltrane",
            album="Giant Steps",
            length_ms=60000,
            track_number=3,
            metadata=TrackMetadata(disc_number=1),
        ),
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=tracks))

    window._update_library_table()

    assert window.library_table.rowCount() == 2
    assert window.library_table.item(0, 0).text() == "Blue Train"
    assert window.library_table.item(1, 2).text() == "Giant Steps"
    assert not window.library_table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable
    assert window.table.rowCount() == 0

    window.library_search.setText("giant steps")

    assert window.library_table.isRowHidden(0)
    assert not window.library_table.isRowHidden(1)


def test_album_mode_groups_tracks_and_opens_detail_on_double_click(app):
    window = MainWindow(start_worker=False)
    tracks = (
        Track(
            track_id=1,
            title="Blue Train",
            artist="John Coltrane",
            album="Blue Train",
            length_ms=60000,
            year=1957,
            track_number=1,
            artwork_id=42,
        ),
        Track(
            track_id=2,
            title="Moment's Notice",
            artist="John Coltrane",
            album="Blue Train",
            length_ms=120000,
            year=1957,
            track_number=2,
        ),
        Track(
            track_id=3,
            title="Naima",
            artist="John Coltrane",
            album="Giant Steps",
            length_ms=90000,
            year=1960,
        ),
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=tracks))
    window._update_library_table()
    window._set_library_mode("album")

    assert window.album_grid.count() == 2
    blue_train = next(
        index
        for index in range(window.album_grid.count())
        if window.album_grid.item(index).data(Qt.ItemDataRole.UserRole).title
        == "Blue Train"
    )
    window._open_album(window.album_grid.item(blue_train))

    assert window.album_detail_stack.currentWidget() is window.album_detail_page
    assert window.album_track_table.rowCount() == 2
    assert window.album_detail_title.text() == "Blue Train"
    assert "1957" in window.album_detail_meta.text()
    window.close()


def test_album_mode_search_filters_album_cards(app):
    window = MainWindow(start_worker=False)
    tracks = (
        Track(
            track_id=1,
            title="Blue Train",
            artist="John Coltrane",
            album="Blue Train",
            length_ms=60000,
        ),
        Track(
            track_id=2,
            title="Naima",
            artist="John Coltrane",
            album="Giant Steps",
            length_ms=60000,
        ),
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=tracks))
    window._update_library_table()
    window._set_library_mode("album")

    window.library_search.setText("naima")

    visible = [
        window.album_grid.item(index).isHidden()
        for index in range(window.album_grid.count())
    ]
    assert visible.count(False) == 1
    window.close()


def test_returning_to_album_mode_shows_grid_instead_of_old_detail(app):
    window = MainWindow(start_worker=False)
    track = Track(
        track_id=1,
        title="Blue Train",
        artist="John Coltrane",
        album="Blue Train",
        length_ms=60000,
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=(track,)))
    window._update_library_table()
    window._set_library_mode("album")
    window._open_album(window.album_grid.item(0))

    window._set_library_mode("list")
    window._set_library_mode("album")

    assert window.album_detail_stack.currentWidget() is window.album_grid
    assert window._open_album_summary is None
    window.close()


def test_library_refresh_leaves_old_album_detail(app):
    window = MainWindow(start_worker=False)
    old = Track(
        track_id=1,
        title="Old Song",
        artist="Artist",
        album="Old Album",
        length_ms=60000,
    )
    window._active = SimpleNamespace(
        candidate=SimpleNamespace(id="old-device"),
        library=SimpleNamespace(tracks=(old,)),
    )
    window._update_library_table()
    window._open_album(window.album_grid.item(0))
    new = Track(
        track_id=2,
        title="New Song",
        artist="Artist",
        album="New Album",
        length_ms=60000,
    )
    active = SimpleNamespace(
        candidate=SimpleNamespace(id="new-device"),
        library=SimpleNamespace(tracks=(new,)),
    )
    window._update_device_info = lambda: None

    window._succeeded("select", Reply(active, active, False))

    assert window.album_detail_stack.currentWidget() is window.album_grid
    assert window._open_album_summary is None
    window.close()


def test_album_artwork_result_updates_grid_and_open_detail(app):
    window = MainWindow(start_worker=False)
    track = Track(
        track_id=1,
        title="Blue Train",
        artist="John Coltrane",
        album="Blue Train",
        length_ms=60000,
        artwork_id=42,
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=(track,)))
    window._update_library_table()
    item = window.album_grid.item(0)
    window._open_album(item)
    window._update_device_info = lambda: None
    window.set_busy(True)
    artwork = ArtworkImage(
        cache_key="test-cover",
        artwork_id=42,
        format_id=1,
        width=2,
        height=2,
        rgb888=bytes((240, 30, 30)) * 4,
    )

    window._succeeded("artwork", Reply(artwork, window._active, False))

    assert not item.data(Qt.ItemDataRole.UserRole + 1).isNull()
    assert window.album_detail_cover.pixmap() is not None
    assert window._busy
    assert not window.import_button.isEnabled()
    window.close()


def test_classic_drop_button_glyphs_render_visible_pixels(app):

    from iOpenPod.GUI.presentation.icons import glyph_icon

    for name in (
        "settings-sliders",
        "refresh",
        "eject",
        "plus",
        "folder",
        "minus",
        "photo",
        "x",
        "album",
        "skip-back",
        "music",
    ):
        image = glyph_icon(name, 19, QColor("#30383b")).pixmap(QSize(19, 19)).toImage()
        assert any(
            image.pixelColor(x, y).alpha() > 0
            for x in range(image.width())
            for y in range(image.height())
        ), name


def test_busy_state_blocks_device_switch_and_edits(app):
    window = MainWindow(start_worker=False)
    window.set_busy(True)
    assert not window.devices.isEnabled()
    assert not window.table.isEnabled()
    assert not window.import_button.isEnabled()
    assert window.cancel_button.isEnabled()
    window.set_busy(False)
    window.close()


def test_library_view_clears_when_device_disconnects(app):
    window = MainWindow(start_worker=False)
    track = Track(
        track_id=1,
        title="Blue Train",
        artist="John Coltrane",
        album="Blue Train",
        length_ms=60000,
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=(track,)))
    window._update_library_table()

    window._succeeded("discover", Reply((), None, False))

    assert window.library_table.rowCount() == 0
    assert window.library_count.text() == song_count(0)
    window.close()


def test_library_view_refreshes_after_import(app):
    window = MainWindow(start_worker=False)
    old_track = Track(
        track_id=1, title="Old", artist="Artist", album="Album", length_ms=60000
    )
    new_track = Track(
        track_id=2, title="New", artist="Artist", album="Album", length_ms=60000
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=(old_track,)))
    window._update_library_table()
    active = SimpleNamespace(library=SimpleNamespace(tracks=(old_track, new_track)))
    window._update_device_info = lambda: None

    window._succeeded("commit", Reply(ImportResult(1, "recovery"), active, False))

    assert window.library_table.rowCount() == 2
    assert window.library_table.item(1, 0).text() == "New"
    window.close()


def test_library_view_refreshes_after_restore(app):
    window = MainWindow(start_worker=False)
    old_track = Track(
        track_id=1, title="Old", artist="Artist", album="Album", length_ms=60000
    )
    imported_track = Track(
        track_id=2, title="Imported", artist="Artist", album="Album", length_ms=60000
    )
    window._active = SimpleNamespace(
        library=SimpleNamespace(tracks=(old_track, imported_track))
    )
    window._update_library_table()
    restored = SimpleNamespace(library=SimpleNamespace(tracks=(old_track,)))
    window._update_device_info = lambda: None

    window._succeeded("restore", Reply(restored, restored, False))

    assert window.library_table.rowCount() == 1
    assert window.library_table.item(0, 0).text() == "Old"
    window.close()


def test_library_delete_selection_uses_track_ids_not_table_order(app):
    window = MainWindow(start_worker=False)
    tracks = (
        Track(track_id=91, title="Second", artist="Artist", album="Album", length_ms=1),
        Track(track_id=27, title="First", artist="Artist", album="Album", length_ms=1),
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=tracks))
    window._update_library_table()
    first_row = next(
        row
        for row in range(window.library_table.rowCount())
        if window.library_table.item(row, 0).text() == "Second"
    )
    window.library_table.selectRow(first_row)
    assert window._selected_library_track_ids() == (91,)
    window.close()


def test_library_delete_selection_excludes_non_music_tracks(app):
    window = MainWindow(start_worker=False)
    music = Track(track_id=1, title="Music", artist="A", album="B", length_ms=1)
    podcast = Track(
        track_id=2,
        title="Podcast",
        artist="A",
        album="B",
        length_ms=1,
        media_types=("podcast",),
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=(music, podcast)))
    window._update_library_table()
    window.library_table.selectAll()
    assert window._selected_library_track_ids() == (1,)
    window.close()


def test_removal_workspace_keeps_package_when_filters_change_and_binds_source(app):
    window = MainWindow(start_worker=False)
    tracks = (
        Track(
            track_id=1,
            title="Blue Train",
            artist="John Coltrane",
            album="Blue Train",
            length_ms=60000,
            genre="Jazz",
            year=1957,
        ),
        Track(
            track_id=2,
            title="A Love Supreme",
            artist="John Coltrane",
            album="A Love Supreme",
            length_ms=60000,
            genre="Jazz",
            year=1965,
        ),
    )
    snapshot = LibrarySnapshot(
        tracks,
        (Playlist(10, "Favorites", entries=(PlaylistEntry("entry", 1),)),),
    )
    window._active = SimpleNamespace(library=snapshot)
    window._update_library_table()
    removal = window.removal_view
    assert removal.matching_ids() == (1, 2)
    removal.add_to_package((1,), "Library selection")
    removal.add_to_package((1,), "Title: blue")
    assert len(removal.package_entries) == 1
    removal.title_filter.setText("love")
    assert removal.matching_ids() == (2,)
    assert tuple(entry.track.track_id for entry in removal.package_entries) == (1,)
    removal.add_to_package((2,), "Title: love")
    assert tuple(entry.track.track_id for entry in removal.package_entries) == (1, 2)

    removal.set_source(snapshot, "same-device", "new-database-revision")

    assert not removal.package_entries
    window.close()


def test_library_view_clears_when_failed_operation_disconnects_device(app):
    window = MainWindow(start_worker=False)
    track = Track(
        track_id=1, title="Old", artist="Artist", album="Album", length_ms=60000
    )
    window._active = SimpleNamespace(library=SimpleNamespace(tracks=(track,)))
    window._update_library_table()
    window._update_device_info = lambda: None

    window._failed("commit", "操作取消", Reply(None, None, False))

    assert window.library_table.rowCount() == 0
    assert window.library_count.text() == song_count(0)
    window.close()


def test_adding_files_preserves_edits_and_selection(app):
    window = MainWindow(start_worker=False)
    window.show_entries((PreviewEntry("old", Path("/tmp/one.mp3"), title="One"),))
    window.table.item(0, 1).setText("Edited")
    window.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    window._add_paths((Path("/tmp/two.mp3"),))
    window._succeeded(
        "preview",
        Reply(
            (
                PreviewEntry("new-token", Path("/tmp/one.mp3"), title="One"),
                PreviewEntry("two", Path("/tmp/two.mp3"), title="Two"),
            ),
            None,
            False,
        ),
    )
    assert window.edited_entries()[0].title == "Edited"
    assert not window.edited_entries()[0].selected
    window.close()


def test_reselecting_same_device_keeps_queue(app):
    window = MainWindow(start_worker=False)
    window._active = object()
    window.show_entries((PreviewEntry("one", Path("/tmp/one.mp3"), title="Edited"),))
    active = type(
        "Active", (), {"candidate": type("Candidate", (), {"id": "device"})()}
    )()
    window._active = active
    window._update_device_info = lambda: None
    window._succeeded("select", Reply(active, active, False))
    assert window.edited_entries()[0].title == "Edited"
    window.close()
