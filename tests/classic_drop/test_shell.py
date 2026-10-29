"""Behavior checks for the native macOS shell using isolated Qt widgets."""

from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import cast

import pytest
from PySide6.QtCore import QEvent, QSize, Qt, QThread
from PySide6.QtGui import QCloseEvent, QColor, QPalette
from PySide6.QtWidgets import QApplication, QToolBar

from classic_drop.engine import PreviewEntry
from classic_drop.i18n import tr
from classic_drop.window import MainWindow
from classic_drop.worker import Reply, Worker
from iOpenPod.app.models.device import ActiveIPod
from iPodDB.library import Track


@pytest.fixture(scope="module")
def app() -> QApplication:
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    return application


def active_library(tracks: tuple[Track, ...]) -> ActiveIPod:
    return cast("ActiveIPod", SimpleNamespace(library=SimpleNamespace(tracks=tracks)))


def test_library_empty_state_distinguishes_connection_and_empty_library(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)

    assert window.library_stack.currentWidget() is window.library_empty_page
    assert window.library_empty_title.text() == tr("No iPod connected")

    window._active = active_library(())
    window._update_library_table()

    assert window.library_stack.currentWidget() is window.library_empty_page
    assert window.library_empty_title.text() == tr("No music on this iPod")
    window.close()


def test_library_empty_search_state_restores_results_when_cleared(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)
    tracks = (
        Track(
            track_id=1,
            title="Blue Train",
            artist="John Coltrane",
            album="Blue Train",
            length_ms=60000,
        ),
    )
    window._active = active_library(tracks)
    window._update_library_table()

    window.library_search.setText("missing")

    assert window.library_stack.currentWidget() is window.library_empty_page
    assert window.library_empty_title.text() == tr("No matching music")

    window.library_search.clear()

    assert window.library_stack.currentWidget() is not window.library_empty_page
    window.close()


def test_import_queue_empty_state_replaces_table_until_entries_exist(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)

    assert window.queue_stack.currentWidget() is window.queue_empty_page

    window.show_entries((PreviewEntry("one", Path("/tmp/one.mp3"), title="One"),))

    assert window.queue_stack.currentWidget() is window.table
    window.show_entries(())
    assert window.queue_stack.currentWidget() is window.queue_empty_page
    window.close()


def test_toolbar_icons_follow_the_host_palette(app: QApplication) -> None:
    window = MainWindow(start_worker=False)
    original_palette = app.palette()
    icon_color = QColor("#f3f4f6")
    dark_palette = QPalette(original_palette)
    dark_palette.setColor(QPalette.ColorRole.ButtonText, icon_color)

    try:
        app.setPalette(dark_palette)
        QApplication.sendEvent(window, QEvent(QEvent.Type.ApplicationPaletteChange))
        image = window.refresh_button.icon().pixmap(QSize(19, 19)).toImage()

        assert any(
            image.pixelColor(x, y) == icon_color
            for y in range(image.height())
            for x in range(image.width())
        )
    finally:
        app.setPalette(original_palette)
        window.close()


def test_sidebar_switches_workspaces_without_resetting_import_edits(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)
    window.show_entries((PreviewEntry("one", Path("/tmp/one.mp3"), title="One"),))
    window._item(0, 1).setText("Edited title")
    requests: list[str] = []
    window.request.connect(lambda command, _payload: requests.append(command))

    window.sidebar.setCurrentRow(1)
    assert window.pages.currentWidget() is window.import_page
    assert window.heading_title.text() == tr("To Import")
    window.sidebar.setCurrentRow(2)
    assert window.pages.currentWidget() is window.recovery_page
    assert not window.restore_button.isEnabled()
    window.sidebar.setCurrentRow(0)

    assert window.pages.currentWidget() is window.library_page
    assert window.edited_entries()[0].title == "Edited title"
    assert not requests
    window.close()


def test_native_toolbar_and_inspector_remain_usable_at_minimum_size(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)
    assert isinstance(window.toolbar, QToolBar)
    window.sidebar.setCurrentRow(1)
    window.resize(940, 580)
    window.show()
    app.processEvents()

    assert window.inspector_stack.isHidden()
    window.inspector_button.click()
    assert not window.inspector_stack.isHidden()
    window.inspector_button.click()
    assert window.inspector_stack.isHidden()
    assert window.import_button.visibleRegion().boundingRect().width() > 0
    window.close()


def test_library_row_selection_updates_read_only_inspector(app: QApplication) -> None:
    window = MainWindow(start_worker=False)
    track = Track(
        track_id=1,
        title="Blue Train",
        artist="John Coltrane",
        album="Blue Train",
        length_ms=60000,
    )
    window._active = active_library((track,))
    window._update_library_table()
    window.library_table.selectRow(0)

    assert window.library_inspector_title.text() == "Blue Train"
    assert "John Coltrane" in window.library_inspector_details.text()
    window.library_search.setText("no match")
    assert window.library_inspector_title.text() != "Blue Train"
    window.close()


def test_busy_close_cancels_then_waits_for_worker_without_ejecting(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)
    window._thread = cast("QThread", SimpleNamespace(isRunning=lambda: True))
    cancelled = Event()
    window.worker = cast("Worker", SimpleNamespace(cancelled=cancelled))
    window.set_busy(True)
    requests: list[str] = []
    window.request.connect(lambda command, _payload: requests.append(command))
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    assert cancelled.is_set()
    assert window._closing
    assert not requests
    window._succeeded("preview", Reply((), None, False))
    assert requests == ["close"]
    window._thread = None
    window.worker = None
    window.close()


def test_recovery_entry_follows_worker_availability_and_busy_state(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)
    window.sidebar.setCurrentRow(2)
    assert not window.restore_button.isEnabled()

    window._succeeded("discard", Reply(None, None, True))
    assert window.restore_button.isEnabled()
    assert window.shell.recovery_title.text() == tr(
        "Last Library change can be restored"
    )
    window.set_busy(True)
    assert not window.restore_button.isEnabled()
    window._succeeded("discard", Reply(None, None, False))
    assert not window.restore_button.isEnabled()
    assert window.shell.recovery_title.text() == tr("No recovery available")
    window.close()


def test_open_and_find_shortcuts_observe_workspace_and_busy_state(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)
    assert window._find_action.isEnabled()
    assert not window._open_action.isEnabled()
    window.sidebar.setCurrentRow(1)
    assert not window._find_action.isEnabled()
    window._active = active_library(())
    window.set_busy(False)
    assert window._open_action.isEnabled()
    window.set_busy(True)
    assert not window._open_action.isEnabled()
    window.close()


def test_sorting_library_keeps_search_and_inspector_bound_to_the_track(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)
    tracks = tuple(
        Track(
            track_id=index, title=title, artist="Artist", album="Album", length_ms=60000
        )
        for index, title in enumerate(("Zulu", "Alpha"), 1)
    )
    window._active = active_library(tracks)
    window._update_library_table()
    window.library_table.sortItems(0, Qt.SortOrder.AscendingOrder)
    window.library_table.selectRow(0)

    assert window.library_inspector_title.text() == "Alpha"
    window.library_search.setText("Alpha")
    assert not window.library_table.isRowHidden(0)
    assert window.library_table.isRowHidden(1)
    window.close()


def test_album_selection_updates_inspector_and_numeric_columns_sort_numerically(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)
    tracks = (
        Track(
            track_id=1,
            title="Long",
            artist="Artist",
            album="Collection",
            length_ms=600000,
        ),
        Track(
            track_id=2,
            title="Short",
            artist="Artist",
            album="Collection",
            length_ms=60000,
        ),
    )
    window._active = active_library(tracks)
    window._update_library_table()
    window.library_table.sortItems(6, Qt.SortOrder.AscendingOrder)
    item = window.library_table.item(0, 0)
    assert item is not None and item.text() == "Short"
    window._set_library_mode("album")
    window.album_grid.setCurrentRow(0)

    assert window.library_inspector_title.text() == "Collection"
    assert "Artist" in window.library_inspector_details.text()
    window.close()
