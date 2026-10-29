import sqlite3
from collections.abc import Iterator
from pathlib import Path
from threading import Event

import pytest

from classic_drop.engine import ClassicDropEngine
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from storage import AccessMode, DevicePath
from tests.classic_drop.test_media import media_file
from tests.iOpenPod.app.services.test_library_resources import Device, build_device


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


def test_explicit_device_recovery_keeps_removed_media_on_ipod(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path, host_recovery=True)
    active = device.active
    removed = active.library.tracks[0]
    workspace = LibraryWorkspace()
    workspace.load(active.library)
    workspace.remove_tracks((removed.track_id,), workspace.edit_revision)
    desired = workspace.desired_snapshot()
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(
            desired, active, 1, 1, delete_omissions=True, device_recovery=True
        ),
        lambda _: None,
        Event(),
    )
    assert review.result.prepared is not None, review.result.issues
    saved = device.coordinator.save_library(
        review, active, lambda _: None, Event(), retain_recovery=True
    )
    assert saved.active is not None, saved.issues
    assert not (device.root / removed.metadata.location).exists()
    with device.storage.open_session(
        device.storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        journal = DevicePath(saved.recovery_path)
        assert session.exists(journal)
        observed = session.inspect_transaction(journal)
        restored = session.restore_transaction(observed)
        session.finalize_transaction(restored.recovery)
    device.assert_original()


def test_classic_drop_remove_tracks_retains_device_recovery_and_restores(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    before = engine.active.library
    removed = before.tracks[0]

    result = engine.remove_tracks((removed.track_id,), Event())

    assert removed.track_id not in {
        track.track_id for track in engine.active.library.tracks
    }
    assert not (device.root / removed.metadata.location).exists()
    assert result.recovery_path.startswith(".iopenpod-recovery/")
    assert engine.history.latest(engine._identity()) == result.recovery_path
    with pytest.raises(ValueError, match="Restore the previous Library change"):
        engine.remove_tracks((before.tracks[1].track_id,), Event())
    engine.restore_last(Event())
    assert engine.active.library == before
    assert (device.root / removed.metadata.location).read_bytes() == device.original[
        removed.metadata.location
    ]


def test_classic_drop_remove_tracks_rejects_an_empty_selection(
    connected: tuple[Device, ClassicDropEngine],
) -> None:
    _device, engine = connected

    try:
        engine.remove_tracks((), Event())
    except ValueError as error:
        assert "Select at least one song" in str(error)
    else:
        raise AssertionError("An empty deletion must not write a transaction")


def test_classic_drop_device_recovery_survives_app_restart(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    before = engine.active.library
    removed = engine.active.library.tracks[0]
    result = engine.remove_tracks((removed.track_id,), Event())
    engine.close()

    reopened = ClassicDropEngine(
        data_directory=tmp_path / "host", coordinator=DeviceCoordinator(device.storage)
    )
    reopened.select(reopened.discover()[0].id)
    assert reopened.history.latest(reopened._identity()) == result.recovery_path
    assert removed.track_id not in {
        track.track_id for track in reopened.active.library.tracks
    }

    reopened.restore_last(Event())

    assert reopened.active.library == before
    assert (device.root / removed.metadata.location).read_bytes() == device.original[
        removed.metadata.location
    ]
    reopened.close()


def test_deletion_recovery_preserves_the_earlier_import_recovery(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    original = engine.active.library
    source = media_file(tmp_path)
    engine.commit(engine.preview((source,), Event()), Event())
    after_import = engine.active.library
    removed = after_import.tracks[0]

    engine.remove_tracks((removed.track_id,), Event())
    with pytest.raises(ValueError, match="Restore the previous Library change"):
        engine.commit(engine.preview((source,), Event()), Event())

    engine.restore_last(Event())
    assert engine.active.library == after_import
    engine.restore_last(Event())
    assert engine.active.library == original
    device.assert_original()


def test_remove_shared_track_keeps_media_referenced_by_retained_track(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path, host_recovery=True, shared_media=True)
    engine = ClassicDropEngine(
        data_directory=tmp_path / "host", coordinator=device.coordinator
    )
    engine.select(engine.discover()[0].id)
    try:
        first, second = engine.active.library.tracks
        assert first.metadata.location == second.metadata.location

        result = engine.remove_tracks((first.track_id,), Event())

        assert tuple(track.track_id for track in engine.active.library.tracks) == (
            second.track_id,
        )
        assert (device.root / second.metadata.location).exists()
        assert result.removed == 1
        engine.restore_last(Event())
        device.assert_original()
    finally:
        engine.close()


def test_committed_deletion_keeps_session_recovery_when_local_index_fails(
    connected: tuple[Device, ClassicDropEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    _device, engine = connected
    removed = engine.active.library.tracks[0]

    def fail_index(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(engine.history, "record_operation", fail_index)
    with pytest.raises(ValueError, match="local recovery index could not be saved"):
        engine.remove_tracks((removed.track_id,), Event())

    assert engine.pending_recovery is not None
    assert removed.track_id not in {
        track.track_id for track in engine.active.library.tracks
    }
    engine.restore_last(Event())
    assert removed.track_id in {
        track.track_id for track in engine.active.library.tracks
    }
