import io
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from classic_drop.engine import ClassicDropEngine, PreviewEntry
from classic_drop.native_backend import NativeBackend
from classic_drop.native_protocol import Result
from tests.classic_drop.test_audio_format import encoded_audio
from tests.classic_drop.test_engine import connected  # noqa: F401
from tests.classic_drop.test_media import media_file
from tests.iOpenPod.app.services.test_library_resources import Device


@pytest.fixture
def backend(connected: tuple[Device, ClassicDropEngine]) -> NativeBackend:  # noqa: F811
    from classic_drop.native_backend import NativeBackend

    return NativeBackend(connected[1])


def call(backend: NativeBackend, command: str, **kwargs: Any) -> Result:
    from classic_drop.native_protocol import Request

    return backend.execute(
        Request("test", command, generation=backend.generation, **kwargs), Event()
    )


def test_artwork_cache_namespace_survives_restart_and_invalidates_database_changes(
    backend: NativeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = backend.state().artwork_cache_key
    assert len(key) == 64
    assert NativeBackend(backend.engine).state().artwork_cache_key == key
    active = backend.engine.active
    connection = backend.engine.coordinator._active
    assert connection is not None
    changed = replace(active.database_fingerprint, sha256="a" * 64)
    monkeypatch.setattr(
        connection, "active_ipod", replace(active, database_fingerprint=changed)
    )
    assert backend.state().artwork_cache_key != key
    monkeypatch.setattr(
        connection, "active_ipod", replace(active, artwork_database_fingerprint=changed)
    )
    assert backend.state().artwork_cache_key != key
    monkeypatch.setattr(backend.engine.coordinator, "_active", None)
    assert backend.state().artwork_cache_key == ""


def test_audio_formats_inspect_real_files_read_only_and_cache_by_generation(
    backend: NativeBackend,
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device, engine = connected
    track = engine.active.library.tracks[0]
    path = device.root / track.metadata.location
    path.write_bytes(encoded_audio(tmp_path, "alac", 96000, 24))
    before = {
        p.relative_to(device.root): p.read_bytes()
        for p in device.root.rglob("*")
        if p.is_file()
    }

    result = call(backend, "audio_formats", ids=(str(track.track_id),))

    row = result.audio_formats[0]
    assert (row.id, row.codec, row.bit_depth, row.sample_rate_hz) == (
        str(track.track_id),
        "ALAC",
        24,
        96000,
    )
    assert before == {
        p.relative_to(device.root): p.read_bytes()
        for p in device.root.rglob("*")
        if p.is_file()
    }
    original = engine.coordinator.open_playback_source

    def unexpected_read(*_args: object) -> None:
        raise AssertionError("Cached audio facts were reread")

    monkeypatch.setattr(engine.coordinator, "open_playback_source", unexpected_read)
    assert (
        call(backend, "audio_formats", ids=(str(track.track_id),)).audio_formats
        == result.audio_formats
    )
    monkeypatch.setattr(engine.coordinator, "open_playback_source", original)
    engine.select(engine.discover()[0].id)
    backend.state()
    path.write_bytes(encoded_audio(tmp_path, "aac", 48000, 16))
    row = call(backend, "audio_formats", ids=(str(track.track_id),)).audio_formats[0]
    assert (row.codec, row.bit_depth, row.sample_rate_hz) == ("AAC", None, 48000)


def test_audio_formats_validate_entire_batch_before_opening_files(
    backend: NativeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_read(*_args: object) -> None:
        raise AssertionError("Invalid request opened device media")

    monkeypatch.setattr(
        backend.engine.coordinator, "open_playback_source", unexpected_read
    )
    track = backend.engine.active.library.tracks[0]
    for ids in [(), (str(track.track_id), "missing"), (str(track.track_id),) * 9]:
        with pytest.raises(ValueError):
            call(backend, "audio_formats", ids=ids)


def test_unreadable_audio_is_unknown_and_does_not_fail_other_rows(
    backend: NativeBackend,
) -> None:
    ids = tuple(str(t.track_id) for t in backend.engine.active.library.tracks)
    rows = call(backend, "audio_formats", ids=ids).audio_formats
    assert len(rows) == len(ids)
    assert all(
        r.codec == "" and r.bit_depth is None and r.sample_rate_hz is None and r.detail
        for r in rows
    )


def test_audio_formats_cancelled_batch_is_not_cached(
    backend: NativeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from classic_drop.engine import OperationCancelledError
    from classic_drop.native_protocol import Request
    from iOpenPod.app.playback.backend import PlaybackSourceError

    cancelled = Event()

    def source(*_args: object) -> None:
        cancelled.set()
        raise PlaybackSourceError("missing")

    monkeypatch.setattr(backend.engine.coordinator, "open_playback_source", source)
    track = backend.engine.active.library.tracks[0]
    request = Request(
        "cancel-test",
        "audio_formats",
        generation=backend.generation,
        ids=(str(track.track_id),),
    )
    with pytest.raises(OperationCancelledError):
        backend.execute(request, cancelled)
    assert not backend.audio_formats


def test_audio_formats_stale_generation_cannot_open_files(
    backend: NativeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from classic_drop.native_protocol import Request

    def source(*_args: object) -> None:
        raise AssertionError("Stale request opened media")

    monkeypatch.setattr(backend.engine.coordinator, "open_playback_source", source)
    with pytest.raises(ValueError, match="generation expired"):
        backend.execute(
            Request("stale", "audio_formats", generation="old", ids=("1",)), Event()
        )


def test_original_alac_native_preview_binds_option_and_keeps_source_bytes(
    backend: NativeBackend, tmp_path: Path
) -> None:
    from classic_drop.native_protocol import Request

    source = tmp_path / "hires.m4a"
    source.write_bytes(encoded_audio(tmp_path, "alac", 96000, 24))
    wire = json.dumps(
        {
            "version": 1,
            "id": "alac",
            "command": "preview",
            "generation": backend.generation,
            "paths": [str(source)],
            "allow_high_resolution_alac": True,
        }
    ).encode()
    result = backend.execute(Request.decode(wire), Event())
    assert result.preview[0].mode == "copy"
    assert result.preview[0].selected
    with pytest.raises(ValueError, match=r"[Cc]lear"):
        call(backend, "preview", paths=(str(source),))
    result = call(backend, "queue")
    assert result.preview[0].mode == "copy"
    call(backend, "discard")
    result = call(backend, "preview", paths=(str(source),))
    assert result.preview[0].mode == "convert"


@pytest.mark.parametrize("value", ["true", 1, None, [], {}])
def test_alac_protocol_option_requires_a_boolean(value: object) -> None:
    from classic_drop.native_protocol import Request

    wire = json.dumps(
        {
            "version": 1,
            "id": "alac",
            "command": "preview",
            "allow_high_resolution_alac": value,
        }
    ).encode()
    with pytest.raises(ValueError):
        Request.decode(wire)


def test_keep_completed_removal_preserves_files_and_current_package_after_preferences_change(
    backend: NativeBackend,
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
    tmp_path: Path,
) -> None:
    from storage import FilePreconditionError

    device, engine = connected
    engine.commit(engine.preview((media_file(tmp_path),), Event()), Event())
    removed = engine.active.library.tracks[0]
    deletion = engine.remove_tracks((removed.track_id,), Event())
    preferences = device.root / "iPod_Control/Device/Preferences"
    preferences.write_bytes(bytes(2960))
    engine.select(engine.discover()[0].id)
    backend.state()
    remaining = engine.active.library.tracks[0]
    call(backend, "package_add", ids=(str(remaining.track_id),))
    with pytest.raises(FilePreconditionError, match="Preferences"):
        engine.restore_last(Event())
    before = backend.state()
    files = {
        path.relative_to(device.root): path.read_bytes()
        for path in device.root.rglob("*")
        if path.is_file()
    }

    result = call(backend, "keep", token=deletion.recovery_path)

    assert result.state.writes_allowed
    assert not result.state.can_restore
    assert result.state.generation == before.generation
    assert result.state.package_count == 1
    assert engine.history.latest_operation(engine._identity()) is None
    assert files == {
        path.relative_to(device.root): path.read_bytes()
        for path in device.root.rglob("*")
        if path.is_file()
    }
    assert removed.track_id not in {t.track_id for t in engine.active.library.tracks}
    assert call(backend, "prepare_delete").review is not None
    from classic_drop.history import ImportHistory

    reopened = ImportHistory(engine.history.path.parent)
    assert reopened.latest_operation(engine._identity()) is None
    with reopened._connection() as db:
        assert db.execute(
            "SELECT operation, kept, restored FROM import_run ORDER BY id"
        ).fetchall() == [("import", 1, 0), ("delete", 1, 0)]


def test_keep_rejects_a_stale_recovery_record_without_unlocking_writes(
    backend: NativeBackend,
) -> None:
    engine = backend.engine
    deletion = engine.remove_tracks(
        (engine.active.library.tracks[0].track_id,), Event()
    )
    backend.state()
    with pytest.raises(ValueError, match="recovery record changed"):
        call(backend, "keep", token="stale")
    assert not backend.state().writes_allowed
    assert engine.history.latest(engine._identity()) == deletion.recovery_path


@pytest.mark.parametrize("invalid", ["pending", "state", "identity", "history"])
def test_keep_refuses_uncertain_or_unrecordable_baselines(
    backend: NativeBackend,
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    import sqlite3

    from storage import StorageError

    device, engine = connected
    deletion = engine.remove_tracks(
        (engine.active.library.tracks[0].track_id,), Event()
    )
    backend.state()
    path = device.root / deletion.recovery_path
    if invalid == "pending":
        engine.pending_recovery = deletion.recovery_path
    elif invalid in {"state", "identity"}:
        journal = json.loads(path.read_bytes())
        journal["state" if invalid == "state" else "volume_id"] = (
            "restored" if invalid == "state" else "another-volume"
        )
        path.write_text(json.dumps(journal))
    else:

        def fail_history(*_args: object) -> None:
            raise sqlite3.OperationalError("disk full")

        monkeypatch.setattr(engine.history, "keep_current", fail_history)

    with pytest.raises((ValueError, StorageError, sqlite3.OperationalError)):
        call(backend, "keep", token=deletion.recovery_path)

    assert not backend.state().writes_allowed
    assert engine.history.latest(engine._identity()) == deletion.recovery_path


def test_paged_tracks_keep_lossless_ids_and_reject_stale_generation(
    backend: NativeBackend,
) -> None:
    page = call(backend, "tracks", limit=1)
    assert len(page.tracks) == 1
    assert page.total >= 2
    assert isinstance(page.tracks[0].id, str)
    from classic_drop.native_protocol import Request

    with pytest.raises(ValueError, match="expired"):
        backend.execute(Request("old", "tracks", generation="old"), Event())


def test_album_details_use_same_library_membership(backend: NativeBackend) -> None:
    albums = call(backend, "albums")
    assert albums.albums
    album = albums.albums[0]
    detail = call(backend, "tracks", album=album.id)
    assert detail.total == album.track_count
    assert sum(t.length_ms for t in detail.tracks) == album.duration_ms


def test_capacity_refresh_preserves_preview_and_library_generation(
    backend: NativeBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
) -> None:
    call(backend, "preview", paths=(str(media_file(tmp_path)),))
    before = backend.state()
    active = backend.engine.active
    tokens = tuple(backend.entries)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        "storage.testing.shutil.disk_usage",
        lambda _: type(usage)(usage.total, usage.used + 4096, usage.free - 4096),
    )
    discovery = connected[0].platform.discover()
    monkeypatch.setattr(
        connected[0].platform,
        "discover",
        lambda: replace(
            discovery,
            observations=tuple(
                replace(
                    observation,
                    volume=replace(
                        observation.volume, available_bytes=usage.free - 4096
                    ),
                )
                for observation in discovery.observations
            ),
        ),
    )

    after = call(backend, "discover").state

    assert backend.engine.active is active
    assert backend.engine.active.library is active.library
    assert after.generation == before.generation
    assert after.revision == before.revision
    assert after.queue_count == before.queue_count == 1
    assert tuple(backend.entries) == tokens
    assert after.available_bytes == usage.free - 4096
    assert call(backend, "albums").total > 0
    assert call(backend, "commit", revision=backend.revision, ids=tokens).count == 1


def test_capacity_refresh_preserves_an_issued_removal_review(
    backend: NativeBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call(
        backend,
        "package_add",
        ids=(str(backend.engine.active.library.tracks[0].track_id),),
    )
    review = call(backend, "prepare_delete").review
    assert review is not None
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        "storage.testing.shutil.disk_usage",
        lambda _: type(usage)(usage.total, usage.used + 4096, usage.free - 4096),
    )

    call(backend, "discover")

    assert call(backend, "review", token=review.token).tracks == review.tracks
    assert call(backend, "delete", token=review.token).count == 1


def test_passive_discovery_invalidates_disconnected_device(
    backend: NativeBackend,
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
) -> None:
    old_generation = backend.generation
    device, _engine = connected
    device.platform.disconnect(device.root)

    state = call(backend, "discover").state

    assert not state.active_id
    assert state.generation != old_generation
    assert not state.writes_allowed


def test_reselection_invalidates_generation_even_for_unchanged_library(
    backend: NativeBackend,
) -> None:
    before = backend.state()

    call(backend, "select", token=backend.engine.active.candidate.id.value)

    assert backend.state().generation != before.generation


def test_preview_edits_are_token_bound_and_commit_preserves_retained_tracks(
    backend: NativeBackend, tmp_path: Path
) -> None:
    from classic_drop.native_protocol import Edit

    old = backend.engine.active.library.tracks
    call(backend, "preview", paths=(str(media_file(tmp_path)),))
    entry = next(iter(backend.entries.values()))
    edit = Edit(
        entry.token,
        "Edited title",
        entry.artist,
        entry.album,
        entry.album_artist,
        entry.track_number,
        entry.disc_number,
        True,
    )
    with pytest.raises(ValueError, match="expired"):
        call(backend, "commit", revision="old", edits=(edit,))
    result = call(backend, "commit", revision=backend.revision, edits=(edit,))
    assert result.count == 1
    assert backend.engine.active.library.tracks[:-1] == old
    assert backend.engine.active.library.tracks[-1].title == "Edited title"
    assert result.state.can_restore
    call(backend, "restore")
    assert backend.engine.active.library.tracks == old


def test_duplicate_override_requires_explicit_authorization(
    backend: NativeBackend, tmp_path: Path
) -> None:
    from classic_drop.native_protocol import Edit

    source = media_file(tmp_path)
    copied = tmp_path / "copy.m4a"
    copied.write_bytes(source.read_bytes())
    call(backend, "preview", paths=(str(source), str(copied)))
    edits = tuple(
        Edit(
            e.token,
            e.title,
            e.artist,
            e.album,
            e.album_artist,
            e.track_number,
            e.disc_number,
            True,
        )
        for e in backend.entries.values()
    )
    with pytest.raises(ValueError, match="duplicate"):
        call(backend, "commit", revision=backend.revision, edits=edits)


def test_review_token_is_single_use_and_invalidated_by_package_changes(
    backend: NativeBackend,
) -> None:
    track_id = str(backend.engine.active.library.tracks[0].track_id)
    call(backend, "package_add", ids=(track_id,), source="Title: example")
    review = call(backend, "prepare_delete").review
    assert review and review.tracks[0].id == track_id
    call(backend, "package_clear")
    with pytest.raises(ValueError, match="expired"):
        call(backend, "delete", token=review.token)


def test_review_rows_use_the_same_order_as_package_pages(
    backend: NativeBackend,
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
) -> None:
    device, engine = connected
    snapshot = engine.active.library
    changed = replace(
        snapshot,
        tracks=tuple(
            replace(
                track,
                title=("Z last" if index == 0 else "A first"),
                album="One album",
                album_artist="One artist",
                track_number=1,
            )
            for index, track in enumerate(snapshot.tracks)
        ),
    )
    result = device.save(device.prepare(changed))
    assert result.active is not None
    engine.select(engine.discover()[0].id)
    backend.state()
    call(
        backend,
        "package_add",
        ids=tuple(str(t.track_id) for t in engine.active.library.tracks),
    )
    page = call(backend, "package")
    review = call(backend, "prepare_delete").review
    assert review is not None
    assert [t.id for t in review.tracks] == [t.id for t in page.tracks]


def test_protocol_rejects_oversized_pages_and_invalid_edits() -> None:
    from classic_drop.native_protocol import Request

    with pytest.raises(ValueError):
        Request.decode(
            json.dumps(
                {"version": 1, "id": "x", "command": "tracks", "limit": 201}
            ).encode()
        )
    with pytest.raises(ValueError):
        Request.decode(b'{"version":2,"id":"x","command":"hello"}')
    with pytest.raises(ValueError):
        Request.decode(
            b'{"version":1,"id":"x","command":"commit","edits":[{"token":"a","selected":"false"}]}'
        )


def test_helper_has_no_gui_application_and_exits_cleanly(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "classic_drop.native_helper",
            "--data-directory",
            str(tmp_path),
        ],
        input='{"version":1,"id":"hello","command":"hello"}\n{"version":1,"id":"close","command":"close"}\n',
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    messages = [json.loads(line) for line in result.stdout.splitlines()]
    hello = next(m for m in messages if m["id"] == "hello")
    assert hello["event"] == "result"
    assert hello["result"]["gui_application"] is False
    assert messages[-1]["id"] == "close"


def test_cancel_reader_reaches_a_busy_serial_worker(tmp_path: Path) -> None:
    from classic_drop.engine import ClassicDropEngine
    from classic_drop.native_helper import HelperServer
    from iOpenPod.app.library_write import WriteProgress
    from tests.iOpenPod.app.services.test_library_resources import build_device

    started = Event()

    class SlowEngine(ClassicDropEngine):
        def preview(
            self,
            paths: tuple[Path, ...],
            cancelled: Event,
            *,
            allow_high_resolution_alac: bool = False,
        ) -> tuple[PreviewEntry, ...]:
            self.progress(WriteProgress("inspect", "Inspecting a long file"))
            started.set()
            while not cancelled.wait(0.01):
                pass
            self._checkpoint(cancelled)
            return ()

    def factory() -> ClassicDropEngine:
        device = build_device(tmp_path)
        engine = SlowEngine(
            data_directory=tmp_path / "host", coordinator=device.coordinator
        )
        engine.select(engine.discover()[0].id)
        return engine

    output = io.StringIO()
    server = HelperServer(output, tmp_path / "host", engine_factory=factory)
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb")
    writer = os.fdopen(write_fd, "wb", buffering=0)
    thread = Thread(target=server.run, args=(stream,))
    thread.start()
    try:
        writer.write(b'{"version":1,"id":"h","command":"hello"}\n')
        deadline = time.monotonic() + 10
        while not output.getvalue() and time.monotonic() < deadline:
            time.sleep(0.01)
        generation = json.loads(output.getvalue().splitlines()[0])["result"]["state"][
            "generation"
        ]
        writer.write(
            (
                json.dumps(
                    {
                        "version": 1,
                        "id": "p",
                        "command": "preview",
                        "generation": generation,
                    }
                )
                + "\n"
            ).encode()
        )
        assert started.wait(5)
        writer.write(b'{"version":1,"id":"c","command":"cancel","token":"p"}\n')
        deadline = time.monotonic() + 3
        while '"cancelled"' not in output.getvalue() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert any(
            m.get("id") == "p" and m.get("code") == "cancelled"
            for m in map(json.loads, output.getvalue().splitlines())
        )
    finally:
        writer.write(b'{"version":1,"id":"close","command":"close"}\n')
        thread.join(5)
        writer.close()
        stream.close()
    assert not thread.is_alive()


def test_native_browser_searches_all_metadata_and_album_members(
    backend: NativeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = backend.engine.active
    tracks = tuple(
        replace(
            t,
            show="Hidden Show",
            metadata=replace(t.metadata, composer="Hidden Composer"),
        )
        for t in active.library.tracks
    )
    updated = replace(active, library=replace(active.library, tracks=tracks))
    connection = backend.engine.coordinator._active
    assert connection is not None
    monkeypatch.setattr(connection, "active_ipod", updated)
    backend.state()
    assert call(backend, "tracks", query="Hidden Composer").total == len(tracks)
    assert call(backend, "albums", query="Hidden Show").albums
    assert call(backend, "tracks", query="Hidden Show").total == len(tracks)


def test_browser_pages_adapt_to_large_metadata(
    backend: NativeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import asdict

    from classic_drop.native_protocol import MAX_MESSAGE, Envelope

    active = backend.engine.active
    tracks = tuple(
        replace(t, metadata=replace(t.metadata, lyrics="界" * 180000))
        for t in active.library.tracks
    )
    connection = backend.engine.coordinator._active
    assert connection is not None
    monkeypatch.setattr(
        connection,
        "active_ipod",
        replace(active, library=replace(active.library, tracks=tracks)),
    )
    backend.state()
    page = call(backend, "tracks")
    assert len(page.tracks) == 1
    assert (
        len(
            json.dumps(
                asdict(Envelope("test", "result", backend.generation, 1, result=page)),
                ensure_ascii=False,
            ).encode()
        )
        < MAX_MESSAGE
    )
    assert "界" * 180000 in page.tracks[0].search_text
    assert call(backend, "tracks", offset=1).tracks[0].id != page.tracks[0].id


def test_album_pages_adapt_without_losing_library_members(
    backend: NativeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import asdict

    from classic_drop.native_protocol import MAX_MESSAGE, Envelope

    active = backend.engine.active
    tracks = tuple(
        replace(
            active.library.tracks[0], track_id=i + 1, album=f"{i:03d}" + "界" * 3000
        )
        for i in range(200)
    )
    connection = backend.engine.coordinator._active
    assert connection is not None
    monkeypatch.setattr(
        connection,
        "active_ipod",
        replace(active, library=replace(active.library, tracks=tracks)),
    )
    backend.state()
    seen: list[str] = []
    while len(seen) < 200:
        page = call(backend, "albums", offset=len(seen))
        assert page.total == 200
        assert page.albums
        assert (
            len(
                json.dumps(
                    asdict(
                        Envelope("test", "result", backend.generation, 1, result=page)
                    ),
                    ensure_ascii=False,
                ).encode()
            )
            < MAX_MESSAGE
        )
        seen.extend(album.title for album in page.albums)
    assert seen == [f"{i:03d}" + "界" * 3000 for i in range(200)]


def test_single_oversized_album_reports_incomplete_cache(
    backend: NativeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = backend.engine.active
    track = replace(active.library.tracks[0], album="界" * 400000)
    connection = backend.engine.coordinator._active
    assert connection is not None
    monkeypatch.setattr(
        connection,
        "active_ipod",
        replace(active, library=replace(active.library, tracks=(track,))),
    )
    backend.state()
    with pytest.raises(ValueError, match="Album metadata record"):
        call(backend, "albums")


def test_async_browser_keeps_discovery_responsive_and_rejects_late_index(
    backend: NativeBackend,
    monkeypatch: pytest.MonkeyPatch,
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
) -> None:
    from classic_drop.native_browser import build_index
    from classic_drop.native_helper import HelperServer
    from classic_drop.native_protocol import Request

    started, release = Event(), Event()

    def slow(snapshot: Any, cancelled: Event, progress: Any) -> Any:
        started.set()
        assert release.wait(5)
        return build_index(snapshot, Event(), progress)

    monkeypatch.setattr("classic_drop.native_helper.build_index", slow)
    output = io.StringIO()
    server = HelperServer(output, None)
    event = Event()
    server.events["prepare"] = event
    request = Request("prepare", "prepare_browser", generation=backend.generation)
    server._prepare_browser(backend, request, event)
    try:
        assert started.wait(3)
        before = backend.generation
        assert call(backend, "discover").state.generation == before
        connected[0].platform.disconnect(connected[0].root)
        call(backend, "discover")
        release.set()
        server.preparations[0].join(3)
        assert backend.browser is None
        assert any(
            m["id"] == "prepare" and m["code"] == "cancelled"
            for m in map(json.loads, output.getvalue().splitlines())
        )
        assert "prepare" not in server.events
    finally:
        release.set()
        for thread in server.preparations:
            thread.join(5)
