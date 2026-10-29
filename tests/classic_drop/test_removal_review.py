from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from classic_drop.engine import ClassicDropEngine
from classic_drop.i18n import get_language_manager
from classic_drop.removal_view import RemovalPackageEntry
from classic_drop.window import MainWindow
from classic_drop.worker import Reply, Worker
from iPodDB.library import LibrarySnapshot
from iPodDB.library.playlists import Playlist, PlaylistEntry
from tests.iOpenPod.app.services.test_library_resources import Device, build_device


@pytest.fixture
def app() -> QApplication:
    instance = QApplication.instance()
    assert instance is None or isinstance(instance, QApplication)
    return instance or QApplication([])


@pytest.fixture
def connected(tmp_path: Path) -> Iterator[tuple[Device, ClassicDropEngine]]:
    device = build_device(tmp_path, host_recovery=True)
    engine = ClassicDropEngine(
        data_directory=tmp_path / "host", coordinator=device.coordinator
    )
    engine.select(engine.discover()[0].id)
    try:
        yield device, engine
    finally:
        engine.close()


def test_removal_request_prepares_before_asking_for_confirmation(
    app: QApplication,
    connected: tuple[Device, ClassicDropEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _device, engine = connected
    window = MainWindow(start_worker=False)
    window._active = engine.active
    window._update_library_table()
    first = engine.active.library.tracks[0]
    window.removal_view.add_to_package((first.track_id,), "Library selection")
    requests: list[tuple[str, object]] = []
    monkeypatch.setattr(
        window, "_submit", lambda command, payload: requests.append((command, payload))
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Cancel
    )
    try:
        window._request_remove_tracks()
        assert len(requests) == 1
        assert requests[0] == (
            "prepare_delete",
            (
                (first.track_id,),
                engine.active.library,
                engine.active.candidate.id.value,
                engine.active.database_fingerprint.sha256,
            ),
        )
    finally:
        window.close()


@pytest.mark.parametrize("accepted", [False, True])
def test_removal_confirmation_submits_only_the_review_that_was_shown(
    app: QApplication,
    connected: tuple[Device, ClassicDropEngine],
    monkeypatch: pytest.MonkeyPatch,
    accepted: bool,
) -> None:
    from classic_drop.removal_review import RemovalReviewDialog

    device, engine = connected
    first = engine.active.library.tracks[0]
    prepared = engine.prepare_removal((first.track_id,), Event())
    window = MainWindow(start_worker=False)
    window._active = engine.active
    window._update_library_table()
    window.removal_view.add_to_package((first.track_id,), "Library selection")
    requests: list[tuple[str, object]] = []
    monkeypatch.setattr(
        window, "_submit", lambda command, payload: requests.append((command, payload))
    )
    monkeypatch.setattr(
        RemovalReviewDialog,
        "exec",
        lambda _self: (
            QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
        ),
    )
    try:
        window._succeeded("prepare_delete", Reply(prepared, engine.active, False))
        assert requests == ([("delete", prepared)] if accepted else [])
        device.assert_original()
    finally:
        window.close()


@pytest.mark.parametrize("change", ["package", "source"])
def test_changing_package_or_source_invalidates_removal_confirmation(
    app: QApplication,
    connected: tuple[Device, ClassicDropEngine],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from classic_drop.removal_review import RemovalReviewDialog

    device, engine = connected
    first = engine.active.library.tracks[0]
    prepared = engine.prepare_removal((first.track_id,), Event())
    window = MainWindow(start_worker=False)
    window._active = engine.active
    window._update_library_table()
    window.removal_view.add_to_package((first.track_id,), "Library selection")
    requests: list[tuple[str, object]] = []
    monkeypatch.setattr(
        window, "_submit", lambda command, payload: requests.append((command, payload))
    )

    def changed_package(_dialog: QDialog) -> int:
        if change == "package":
            window.removal_view.clear_package()
        else:
            window._active = None
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(RemovalReviewDialog, "exec", changed_package)
    try:
        window._succeeded("prepare_delete", Reply(prepared, engine.active, False))
        assert not requests
        device.assert_original()
    finally:
        window.close()


@pytest.mark.parametrize("language", ["en", "zh_CN", "ja_JP"])
def test_full_removal_review_preserves_user_metadata_and_return_cancels(
    app: QApplication,
    connected: tuple[Device, ClassicDropEngine],
    language: str,
) -> None:
    from classic_drop.removal_review import RemovalReviewDialog

    _device, engine = connected
    get_language_manager(app).set_language(language)
    first = engine.active.library.tracks[0]
    prepared = engine.prepare_removal((first.track_id,), Event())
    tracks = tuple(
        replace(first, track_id=index, title=f"<曲目 {index}>")
        for index in range(1, 16)
    )
    prepared = replace(
        prepared,
        source=replace(engine.active, library=LibrarySnapshot(tracks)),
        track_ids=tuple(range(1, 16)),
    )
    entries = tuple(RemovalPackageEntry(track, "用户筛选") for track in tracks)
    dialog = RemovalReviewDialog(prepared, entries)
    try:
        assert dialog.table.rowCount() == 15
        title = dialog.table.item(14, 0)
        source = dialog.table.item(14, 3)
        assert title is not None and title.text() == "<曲目 15>"
        assert source is not None and source.text() == "用户筛选"
        assert not dialog.remove_button.isDefault()
        assert dialog.cancel_button.isDefault()
        assert "15" in dialog.remove_button.text()
        assert (
            dialog.scope_label.text()
            != "These songs will be removed from the entire Library and all Playlists. Original music files remain on the iPod for recovery; device space will not be freed immediately."
            or language == "en"
        )
        dialog.show()
        app.processEvents()
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        assert not dialog.isVisible()
        assert dialog.result() == QDialog.DialogCode.Rejected
    finally:
        dialog.close()


def test_removal_editor_is_disabled_while_preparing(app: QApplication) -> None:
    window = MainWindow(start_worker=False)
    try:
        window.set_busy(True)
        assert not window.removal_view.isEnabled()
    finally:
        window.close()


def test_all_affected_playlists_can_be_reviewed_when_names_overflow(
    app: QApplication, connected: tuple[Device, ClassicDropEngine]
) -> None:
    from classic_drop.removal_review import RemovalReviewDialog

    _device, engine = connected
    first = engine.active.library.tracks[0]
    prepared = engine.prepare_removal((first.track_id,), Event())
    playlists = tuple(
        Playlist(
            index,
            f"Affected Playlist {index:03d} with a descriptive name",
            entries=(PlaylistEntry(f"entry-{index}", first.track_id),),
        )
        for index in range(100)
    )
    prepared = replace(
        prepared,
        source=replace(engine.active, library=LibrarySnapshot((first,), playlists)),
    )
    dialog = RemovalReviewDialog(
        prepared, (RemovalPackageEntry(first, "Library selection"),)
    )
    try:
        dialog.show()
        app.processEvents()
        assert dialog.playlist_list.count() == 100
        assert dialog.playlist_list.verticalScrollBar().maximum() > 0
        last = dialog.playlist_list.item(99)
        assert last.text() == "Affected Playlist 099 with a descriptive name"
        dialog.playlist_list.scrollToItem(last)
        app.processEvents()
        assert (
            dialog.playlist_list.viewport()
            .rect()
            .contains(dialog.playlist_list.visualItemRect(last))
        )
    finally:
        dialog.close()


def test_worker_prepares_without_writing_then_commits_review(
    app: QApplication, connected: tuple[Device, ClassicDropEngine]
) -> None:
    device, engine = connected
    active = engine.active
    first = active.library.tracks[0]
    worker = Worker()
    worker.engine = engine
    replies: list[tuple[str, Reply]] = []
    failures: list[object] = []
    worker.succeeded.connect(lambda command, reply: replies.append((command, reply)))
    worker.failed.connect(lambda _command, message, _reply: failures.append(message))
    worker.execute(
        "prepare_delete",
        (
            (first.track_id,),
            active.library,
            active.candidate.id.value,
            active.database_fingerprint.sha256,
        ),
    )
    assert not failures
    assert len(replies) == 1
    device.assert_original()
    worker.execute("delete", replies[0][1].value)
    assert not failures
    assert len(replies) == 2
    assert first.track_id not in {
        track.track_id for track in engine.active.library.tracks
    }
