"""Reviewed Playlist/import transactions over real virtual-device resources."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from classic_drop.engine import ClassicDropEngine, OperationCancelledError
from classic_drop.library_changes import (
    ExistingTrackSelection,
    ImportDestination,
    ImportQueueState,
)
from classic_drop.playlists import PlaylistAction, PlaylistEdit, PlaylistSession
from iOpenPod.app.library_write import WriteProgress
from iPodDB.library import PlaylistKind, SmartPlaylist
from tests.classic_drop.test_media import media_file
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iPodDB.sidecars.test_sidecar_readers import counts, otg


@pytest.fixture
def connected(tmp_path: Path) -> Iterator[tuple[Device, ClassicDropEngine]]:
    device = build_device(tmp_path)
    engine = ClassicDropEngine(
        data_directory=tmp_path / "host", coordinator=device.coordinator
    )
    engine.select(engine.discover()[0].id)
    try:
        yield device, engine
    finally:
        engine.close()


def create(
    session: PlaylistSession,
    name: str = "Road",
    *,
    kind: PlaylistKind = PlaylistKind.PLAYLIST,
) -> int:
    result = session.edit(
        PlaylistEdit(PlaylistAction.CREATE, name=name, kind=kind),
        expected_revision=session.revision,
    )
    assert result.playlist is not None
    return result.playlist.playlist_id


def test_playlist_create_save_maps_identity_without_touching_media(
    connected: tuple[Device, ClassicDropEngine],
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    draft_id = create(session)
    original = engine.active.library
    before = {p: data for p, data in device.original.items() if "iTunes" not in p}
    review = engine.library_changes.prepare(session, (), ImportDestination(), Event())
    assert session.dirty and session.snapshot.tracks == original.tracks
    device.assert_original()
    result = engine.library_changes.save(review, Event())
    saved_id = dict(result.playlist_ids)[draft_id]
    assert saved_id > 0
    assert any(
        p.playlist_id == saved_id and p.name == "Road"
        for p in result.active.library.playlists
    )
    assert result.active.library.tracks == original.tracks
    assert all((device.root / p).read_bytes() == data for p, data in before.items())
    assert engine.history.latest_operation(engine._identity()) == (
        result.recovery_path,
        "playlist",
    )


def test_playlist_rename_delete_and_restore_preserve_tracks(
    connected: tuple[Device, ClassicDropEngine],
) -> None:
    device, engine = connected
    original = engine.active.library
    session = PlaylistSession(original)
    draft_id = create(session)
    saved = engine.library_changes.save(
        engine.library_changes.prepare(session, (), ImportDestination(), Event()),
        Event(),
    )
    playlist_id = dict(saved.playlist_ids)[draft_id]
    session = PlaylistSession(engine.active.library)
    session.edit(
        PlaylistEdit(PlaylistAction.UPDATE, playlist_id, name="Night"),
        expected_revision=session.revision,
    )
    engine.library_changes.save(
        engine.library_changes.prepare(session, (), ImportDestination(), Event()),
        Event(),
    )
    assert any(p.name == "Night" for p in engine.active.library.playlists)
    session = PlaylistSession(engine.active.library)
    session.edit(
        PlaylistEdit(PlaylistAction.DELETE, playlist_id),
        expected_revision=session.revision,
    )
    engine.library_changes.save(
        engine.library_changes.prepare(session, (), ImportDestination(), Event()),
        Event(),
    )
    assert all(p.playlist_id != playlist_id for p in engine.active.library.playlists)
    assert engine.active.library.tracks == original.tracks
    engine.restore_last(Event())
    assert any(p.name == "Night" for p in engine.active.library.playlists)
    for path, data in device.original.items():
        if "iTunes" not in path:
            assert (device.root / path).read_bytes() == data


def test_noop_save_has_no_transaction_or_history(
    connected: tuple[Device, ClassicDropEngine],
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    review = engine.library_changes.prepare(session, (), ImportDestination(), Event())
    assert review.no_changes
    result = engine.library_changes.save(review, Event())
    assert result.recovery_path == ""
    assert engine.history.latest_operation(engine._identity()) is None
    device.assert_original()


@pytest.mark.parametrize("destination_kind", ["library", "existing", "new"])
def test_import_destinations_join_the_same_reviewed_transaction(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path, destination_kind: str
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    folder_id = create(session, "Trips", kind=PlaylistKind.FOLDER)
    existing_id = create(session)
    destination = (
        ImportDestination(playlist_ids=(existing_id,))
        if destination_kind == "existing"
        else ImportDestination(new_name="Imported", parent_id=folder_id)
        if destination_kind == "new"
        else ImportDestination()
    )
    entries = engine.preview((media_file(tmp_path),), Event())
    review = engine.library_changes.prepare(session, entries, destination, Event())
    device.assert_original()
    result = engine.library_changes.save(review, Event())
    assert result.added == 1
    added = engine.active.library.tracks[-1]
    if destination_kind == "existing":
        target = next(
            p
            for p in engine.active.library.playlists
            if p.playlist_id == dict(result.playlist_ids)[existing_id]
        )
        assert target.track_ids == (added.track_id,)
    elif destination_kind == "new":
        target = next(
            p for p in engine.active.library.playlists if p.name == "Imported"
        )
        assert target.track_ids == (added.track_id,)
        assert target.parent_id == dict(result.playlist_ids)[folder_id]
    engine.restore_last(Event())
    device.assert_original()
    assert not (device.root / added.metadata.location).exists()


def test_review_expires_after_session_or_bound_queue_edit(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    entries = engine.preview((media_file(tmp_path),), Event())
    state = ImportQueueState("queue1", entries)
    engine.library_changes.bind_queue(lambda: state)
    review = engine.library_changes.prepare(
        session, entries, state.destination, Event()
    )
    state = replace(
        state, revision="queue2", entries=(replace(entries[0], title="Changed"),)
    )
    with pytest.raises(ValueError, match="queue"):
        engine.library_changes.save(review, Event())
    device.assert_original()
    state = replace(state, revision="queue3")
    review = engine.library_changes.prepare(
        session, state.entries, state.destination, Event()
    )
    create(session)
    with pytest.raises(ValueError, match="draft"):
        engine.library_changes.save(review, Event())
    device.assert_original()


def test_all_existing_import_requires_content_verified_track_selection(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    source = media_file(tmp_path)
    engine.commit(engine.preview((source,), Event()), Event())
    track = engine.active.library.tracks[-1]
    entries = engine.preview((source,), Event())
    entries = (replace(entries[0], selected=True),)
    session = PlaylistSession(engine.active.library)
    playlist_id = create(session)
    reuse = (ExistingTrackSelection(entries[0].token, track.track_id),)
    review = engine.library_changes.prepare(
        session,
        entries,
        ImportDestination(playlist_ids=(playlist_id,)),
        Event(),
        reuse=reuse,
    )
    result = engine.library_changes.save(review, Event())
    assert result.added == 0 and result.reused == 1
    assert engine.active.library.tracks == session.original_snapshot.tracks
    saved_id = dict(result.playlist_ids)[playlist_id]
    assert next(
        p for p in engine.active.library.playlists if p.playlist_id == saved_id
    ).track_ids == (track.track_id,)
    operation = engine.history.latest_operation(engine._identity())
    assert operation is not None and operation[1] == "import"
    assert (device.root / track.metadata.location).read_bytes() == source.read_bytes()


def test_playlist_only_save_preserves_queued_host_intent_and_expires_tokens(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    _device, engine = connected
    entries = engine.preview((media_file(tmp_path),), Event())
    entries = (replace(entries[0], title="My title"),)
    session = PlaylistSession(engine.active.library)
    draft_id = create(session)
    state = ImportQueueState(
        "queue1",
        entries,
        ImportDestination(playlist_ids=(draft_id,)),
        source=engine.active,
    )
    engine.library_changes.bind_queue(lambda: state)
    original_tracks = engine.active.library.tracks
    review = engine.library_changes.prepare(session, (), ImportDestination(), Event())
    result = engine.library_changes.save(review, Event())
    carryover = result.queue_carryover
    assert carryover is not None
    assert carryover.destination is not None
    assert carryover.destination.playlist_ids == (dict(result.playlist_ids)[draft_id],)
    assert not carryover.requires_reselection
    assert carryover.intents[0].entry.title == "My title"
    assert carryover.intents[0].entry.path == entries[0].path
    assert carryover.intents[0].entry.token == ""
    assert engine.active.library.tracks == original_tracks
    with pytest.raises(ValueError, match=r"preview|expired"):
        engine.validate_import_entries(entries, Event())


def test_changed_host_source_revokes_review_even_if_content_returns(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    source = media_file(tmp_path)
    original = source.read_bytes()
    entries = engine.preview((source,), Event())
    session = PlaylistSession(engine.active.library)
    review = engine.library_changes.prepare(
        session, entries, ImportDestination(), Event()
    )
    source.write_bytes(original + b"changed")
    with pytest.raises(ValueError, match="changed"):
        engine.library_changes.save(review, Event())
    source.write_bytes(original)
    with pytest.raises(ValueError, match="expired"):
        engine.library_changes.save(review, Event())
    device.assert_original()


def test_latest_removal_blocks_playlist_preparation(
    connected: tuple[Device, ClassicDropEngine],
) -> None:
    device, engine = connected
    engine.remove_tracks((engine.active.library.tracks[0].track_id,), Event())
    session = PlaylistSession(engine.active.library)
    create(session)
    with pytest.raises(ValueError, match="Restore"):
        engine.library_changes.prepare(session, (), ImportDestination(), Event())
    engine.restore_last(Event())
    device.assert_original()


def test_cancelled_check_keeps_draft_and_host_preparation(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    entries = engine.preview((media_file(tmp_path),), Event())
    session = PlaylistSession(engine.active.library)
    create(session)
    desired, revision = session.snapshot, session.revision
    cancelled = Event()
    cancelled.set()
    with pytest.raises(OperationCancelledError):
        engine.library_changes.prepare(session, entries, ImportDestination(), cancelled)
    assert session.snapshot == desired and session.revision == revision
    assert engine.validate_import_entries(entries, Event())
    device.assert_original()


def test_failed_source_preparation_does_not_save_half_a_batch(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    invalid = tmp_path / "invalid.m4a"
    invalid.write_bytes(b"not an audio file")
    entries = engine.preview((media_file(tmp_path), invalid), Event())
    selected = tuple(replace(entry, selected=True) for entry in entries)
    session = PlaylistSession(engine.active.library)
    create(session)
    with pytest.raises(ValueError, match="expired"):
        engine.library_changes.prepare(session, selected, ImportDestination(), Event())
    assert session.dirty
    assert engine.history.latest_operation(engine._identity()) is None
    device.assert_original()


def test_playlist_review_includes_captured_history_and_otg(
    connected: tuple[Device, ClassicDropEngine],
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    first = session.snapshot.playlists[0]
    session.edit(
        PlaylistEdit(PlaylistAction.UPDATE, first.playlist_id, name="Reviewed"),
        expected_revision=session.revision,
    )
    directory = device.root / "iPod_Control/iTunes"
    data = counts(((3, 0, 500),), width=12)
    (directory / "Play Counts").write_bytes(data)
    (directory / "OTGPlaylistInfo").write_bytes(otg((1, 0, 1)))
    review = engine.library_changes.prepare(session, (), ImportDestination(), Event())
    assert any(
        change.subject == "track" and "play_count" in change.fields
        for change in review.sidecar_changes
    )
    assert any(
        change.name == "On-The-Go 1" and change.action == "add"
        for change in review.sidecar_changes
    )
    assert engine.active.library.tracks[0].play_count == 0
    assert (directory / "Play Counts").read_bytes() == data
    result = engine.library_changes.save(review, Event())
    assert result.active.library.tracks[0].play_count == 3
    assert result.active.library.tracks[0].metadata.bookmark_time_ms == 500
    assert result.active.library.playlists[-1].track_ids == (2, 1, 2)
    assert not (directory / "Play Counts").exists()
    engine.restore_last(Event())
    device.assert_original()
    assert (directory / "Play Counts").read_bytes() == data


def test_sidecar_change_after_review_prevents_save_and_replay(
    connected: tuple[Device, ClassicDropEngine],
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    create(session)
    review = engine.library_changes.prepare(session, (), ImportDestination(), Event())
    path = device.root / "iPod_Control/iTunes/Play Counts"
    path.write_bytes(counts(((3, 0, 0),), width=12))
    with pytest.raises(ValueError):
        engine.library_changes.save(review, Event())
    path.unlink()
    with pytest.raises(ValueError, match="expired"):
        engine.library_changes.save(review, Event())
    device.assert_original()


def test_uncertain_save_retains_recovery_and_never_replays(
    connected: tuple[Device, ClassicDropEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    create(session)
    review = engine.library_changes.prepare(session, (), ImportDestination(), Event())
    save = engine.coordinator.save_library

    def lose_acknowledgement(*args: Any, **kwargs: Any) -> Any:
        return replace(save(*args, **kwargs), active=None)

    monkeypatch.setattr(engine.coordinator, "save_library", lose_acknowledgement)
    with pytest.raises(ValueError, match="Recovery record"):
        engine.library_changes.save(review, Event())
    assert engine.pending_recovery
    assert session.dirty and not session.locked
    with pytest.raises(ValueError, match="Restore"):
        engine.library_changes.save(review, Event())
    engine.restore_last(Event())
    device.assert_original()


def test_unbound_snapshot_cannot_omit_retained_tracks(
    connected: tuple[Device, ClassicDropEngine],
) -> None:
    device, engine = connected
    filtered = replace(engine.active.library, tracks=engine.active.library.tracks[1:])
    session = PlaylistSession(filtered)
    create(session)
    with pytest.raises(ValueError, match="source"):
        engine.library_changes.prepare(session, (), ImportDestination(), Event())
    device.assert_original()


@pytest.mark.parametrize("changed", ["draft", "queue"])
def test_edit_during_preparation_cannot_bind_old_candidate_to_new_revision(
    connected: tuple[Device, ClassicDropEngine], changed: str
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    create(session)
    state = ImportQueueState("q1")
    engine.library_changes.bind_queue(lambda: state)

    def edit_during_check(event: WriteProgress) -> None:
        nonlocal state
        if event.phase != "draft.analysis":
            return
        if changed == "draft":
            create(session, "Later edit")
        else:
            state = replace(state, revision="q2")

    engine.progress = edit_during_check
    with pytest.raises(ValueError, match=changed):
        engine.library_changes.prepare(session, (), ImportDestination(), Event())
    device.assert_original()


@pytest.mark.parametrize("changed", ["draft", "queue"])
def test_save_locks_draft_and_rechecks_queue_before_publication(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path, changed: str
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    entries = engine.preview((media_file(tmp_path),), Event())
    state = ImportQueueState("q1", entries)
    engine.library_changes.bind_queue(lambda: state)
    review = engine.library_changes.prepare(
        session, entries, state.destination, Event()
    )

    def edit_during_save(event: WriteProgress) -> None:
        nonlocal state
        if event.phase != "source.verify":
            return
        if changed == "draft":
            create(session, "Too late")
        else:
            state = replace(state, revision="q2")

    engine.progress = edit_during_save
    with pytest.raises(ValueError, match=r"save|queue"):
        engine.library_changes.save(review, Event())
    assert not session.locked
    device.assert_original()


def test_unresolved_duplicate_copy_requires_explicit_authorization(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    source = media_file(tmp_path)
    engine.commit(engine.preview((source,), Event()), Event())
    entries = tuple(
        replace(entry, selected=True) for entry in engine.preview((source,), Event())
    )
    session = PlaylistSession(engine.active.library)
    before = engine.active.library.tracks
    with pytest.raises(ValueError, match="duplicate"):
        engine.library_changes.prepare(session, entries, ImportDestination(), Event())
    review = engine.library_changes.prepare(
        session,
        entries,
        ImportDestination(),
        Event(),
        allow_duplicates=(entries[0].token,),
    )
    result = engine.library_changes.save(review, Event())
    assert result.added == 1 and len(result.active.library.tracks) == len(before) + 1
    assert result.active.library.tracks[:-1] == before
    engine.restore_last(Event())
    assert engine.active.library.tracks == before
    engine.restore_last(Event())
    device.assert_original()


def test_selected_existing_track_is_verified_by_content_not_title(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    entries = engine.preview((media_file(tmp_path),), Event())
    session = PlaylistSession(engine.active.library)
    wrong_id = engine.active.library.tracks[0].track_id
    with pytest.raises(ValueError, match="source content"):
        engine.library_changes.prepare(
            session,
            entries,
            ImportDestination(),
            Event(),
            reuse=(ExistingTrackSelection(entries[0].token, wrong_id),),
        )
    device.assert_original()


@pytest.mark.parametrize("kind", [PlaylistKind.FOLDER, PlaylistKind.SMART])
def test_folder_and_smart_playlist_reject_manual_import_membership(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path, kind: PlaylistKind
) -> None:
    device, engine = connected
    session = PlaylistSession(engine.active.library)
    target_id = create(session, kind=kind)
    entries = engine.preview((media_file(tmp_path),), Event())
    with pytest.raises(ValueError, match="ordinary Playlist"):
        engine.library_changes.prepare(
            session, entries, ImportDestination(playlist_ids=(target_id,)), Event()
        )
    assert session.dirty
    device.assert_original()


def test_new_empty_destination_requires_explicit_keep_choice(
    connected: tuple[Device, ClassicDropEngine],
) -> None:
    _device, engine = connected
    session = PlaylistSession(engine.active.library)
    with pytest.raises(ValueError, match="empty new Playlist"):
        engine.library_changes.prepare(
            session, (), ImportDestination(new_name="Empty"), Event()
        )
    review = engine.library_changes.prepare(
        session, (), ImportDestination(new_name="Empty", keep_empty_new=True), Event()
    )
    result = engine.library_changes.save(review, Event())
    assert any(
        playlist.name == "Empty" and not playlist.entries
        for playlist in result.active.library.playlists
    )


def test_import_review_lists_smart_membership_refresh(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    _device, engine = connected
    session = PlaylistSession(engine.active.library)
    smart = session.edit(
        PlaylistEdit(
            PlaylistAction.CREATE,
            name="All",
            kind=PlaylistKind.SMART,
            smart=SmartPlaylist(),
        ),
        expected_revision=session.revision,
    ).playlist
    assert smart is not None
    entries = engine.preview((media_file(tmp_path),), Event())
    review = engine.library_changes.prepare(
        session, entries, ImportDestination(), Event()
    )
    assert [
        (change.record_id, change.fields) for change in review.smart_refresh_changes
    ] == [(smart.playlist_id, ("entries",))]
    assert session.playlist(smart.playlist_id).track_ids == (1, 2)
    result = engine.library_changes.save(review, Event())
    saved = next(
        playlist
        for playlist in result.active.library.playlists
        if playlist.playlist_id == dict(result.playlist_ids)[smart.playlist_id]
    )
    assert saved.track_ids == tuple(
        track.track_id for track in result.active.library.tracks
    )


def test_deleted_queued_destination_needs_reselection_without_name_fallback(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    _device, engine = connected
    entries = engine.preview((media_file(tmp_path),), Event())
    session = PlaylistSession(engine.active.library)
    removed = create(session, "Same name")
    create(session, "Same name")
    session.edit(
        PlaylistEdit(PlaylistAction.DELETE, removed), expected_revision=session.revision
    )
    state = ImportQueueState(
        "q1", entries, ImportDestination(playlist_ids=(removed,)), source=engine.active
    )
    engine.library_changes.bind_queue(lambda: state)
    result = engine.library_changes.save(
        engine.library_changes.prepare(session, (), ImportDestination(), Event()),
        Event(),
    )
    assert result.queue_carryover is not None
    assert result.queue_carryover.requires_reselection
    assert result.queue_carryover.destination is None


def test_reprepare_preserved_host_intents_issues_fresh_source_tokens(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    _device, engine = connected
    entries = engine.preview((media_file(tmp_path),), Event())
    entries = (replace(entries[0], title="User title", disc_number=3),)
    state = ImportQueueState("q1", entries)
    engine.library_changes.bind_queue(lambda: state)
    session = PlaylistSession(engine.active.library)
    create(session)
    result = engine.library_changes.save(
        engine.library_changes.prepare(session, (), ImportDestination(), Event()),
        Event(),
    )
    assert result.queue_carryover is not None
    fresh = engine.library_changes.reprepare_intents(result.queue_carryover, Event())
    assert fresh[0].token and fresh[0].token != entries[0].token
    assert fresh[0].title == "User title" and fresh[0].disc_number == 3
    assert fresh[0].path == entries[0].path
    assert engine.validate_import_entries(fresh, Event())


def test_noop_playlist_save_keeps_current_queue_preparation(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    _device, engine = connected
    entries = engine.preview((media_file(tmp_path),), Event())
    state = ImportQueueState("q1", entries)
    engine.library_changes.bind_queue(lambda: state)
    session = PlaylistSession(engine.active.library)
    result = engine.library_changes.save(
        engine.library_changes.prepare(session, (), ImportDestination(), Event()),
        Event(),
    )
    assert result.queue_carryover is None
    assert engine.validate_import_entries(entries, Event())


def test_queue_from_old_active_source_cannot_map_same_numeric_destination(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    _device, engine = connected
    old_active = engine.active
    entries = engine.preview((media_file(tmp_path),), Event())
    old_target = old_active.library.playlists[0].playlist_id
    state = ImportQueueState(
        "q1", entries, ImportDestination(playlist_ids=(old_target,)), source=old_active
    )
    engine.commit(entries, Event())
    engine.library_changes.bind_queue(lambda: state)
    session = PlaylistSession(engine.active.library)
    create(session)
    result = engine.library_changes.save(
        engine.library_changes.prepare(session, (), ImportDestination(), Event()),
        Event(),
    )
    assert result.queue_carryover is not None
    assert result.queue_carryover.destination is None
    assert result.queue_carryover.requires_reselection


def test_playlist_save_carryover_retains_original_alac_batch_policy(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    from classic_drop.audio_format import inspect_audio_format
    from tests.classic_drop.test_audio_format import Source, encoded_audio

    _device, engine = connected
    path = tmp_path / "original-alac.m4a"
    path.write_bytes(encoded_audio(tmp_path, "alac", 96000, 24))
    entries = engine.preview((path,), Event(), allow_high_resolution_alac=True)
    state = ImportQueueState("q1", entries, source=engine.active)
    engine.library_changes.bind_queue(lambda: state)
    session = PlaylistSession(engine.active.library)
    create(session)
    result = engine.library_changes.save(
        engine.library_changes.prepare(session, (), ImportDestination(), Event()),
        Event(),
    )
    assert result.queue_carryover is not None
    fresh = engine.library_changes.reprepare_intents(result.queue_carryover, Event())
    assert fresh[0].mode == "copy"
    prepared = engine.validate_import_entries(fresh, Event())
    song = prepared[0][1].song
    observed = inspect_audio_format(
        Source(Path(song.source.source.path).read_bytes()), checkpoint=lambda: None
    )
    assert (observed.bit_depth, observed.sample_rate_hz) == (24, 96000)
