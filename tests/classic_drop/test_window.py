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
from iPodDB.library import Track, TrackMetadata


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
