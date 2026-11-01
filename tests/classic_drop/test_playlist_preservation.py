"""Retained native data and queued destinations survive reviewed Playlist saves."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from classic_drop.engine import ClassicDropEngine
from classic_drop.library_changes import ImportDestination, ImportQueueState
from classic_drop.playlists import PlaylistAction, PlaylistEdit, PlaylistSession
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartRawRuleData,
    MhodSmartRule,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import PlaylistKind
from tests.classic_drop.test_media import media_file
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iPodDB.library.test_playlists import _smart


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


def _create(session: PlaylistSession, name: str, kind: PlaylistKind) -> int:
    result = session.edit(
        PlaylistEdit(PlaylistAction.CREATE, name=name, kind=kind),
        expected_revision=session.revision,
    )
    assert result.playlist is not None
    return result.playlist.playlist_id


def _rule_bytes(data: bytes) -> tuple[bytes, ...]:
    return tuple(
        data[
            row.chunk.offset : row.chunk.offset
            + row.chunk.generic_header.length_or_child_count
        ]
        for row in parse_iTunesDB(data).find_chunks(MhodHeader)
        if row.chunk.header.mhod_type == MhodType.SMART_PLAYLIST_RULES
    )


def test_merged_import_retains_unknown_smart_rule_bytes_and_saved_occurrences(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    database_path = device.root / "iPod_Control/iTunes/iTunesDB"
    target_id = engine.active.library.playlists[0].playlist_id
    database = parse_iTunesDB(database_path.read_bytes())
    unknown = _smart(
        MhodSmartRule(
            0xFFFF, 1, 0, bytes(range(40)), MhodSmartRawRuleData(b"future rule")
        )
    )
    for row in database.find_chunks(MhypHeader):
        if row.chunk.header.playlist_id == target_id:
            database = database.replace_chunk(
                row, replace(row.chunk, children=(*unknown, *row.chunk.children))
            )
    native = write_iTunesDB(database)
    database_path.write_bytes(native)
    expected_rules = _rule_bytes(native)
    assert expected_rules
    engine.select(engine.active.candidate.id)
    original = next(
        playlist
        for playlist in engine.active.library.playlists
        if playlist.playlist_id == target_id
    )
    assert original.smart is not None and not original.smart.editable
    session = PlaylistSession(engine.active.library)
    _create(session, "Unrelated", PlaylistKind.PLAYLIST)
    entries = engine.preview((media_file(tmp_path),), Event())
    review = engine.library_changes.prepare(
        session, entries, ImportDestination(), Event()
    )
    assert database_path.read_bytes() == native
    saved = engine.library_changes.save(review, Event())
    retained = next(
        playlist
        for playlist in saved.active.library.playlists
        if playlist.playlist_id == target_id
    )
    assert retained.smart == original.smart
    assert retained.entries == original.entries
    # The writer may supply the missing dataset-2 mirror. Every retained or
    # mirrored rule must still reproduce the original opaque bytes exactly.
    assert set(_rule_bytes(database_path.read_bytes())) == set(expected_rules)
    assert len(saved.active.library.tracks) == len(session.original_snapshot.tracks) + 1


def test_merged_import_preserves_retained_artwork_payload_and_track_references(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    device, engine = connected
    thumbnails = {
        path: data for path, data in device.original.items() if path.endswith(".ithmb")
    }
    assert thumbnails
    original_tracks = engine.active.library.tracks
    session = PlaylistSession(engine.active.library)
    _create(session, "Artwork stays", PlaylistKind.PLAYLIST)
    entries = engine.preview((media_file(tmp_path),), Event())
    assert entries[0].artwork is not None
    review = engine.library_changes.prepare(
        session, entries, ImportDestination(), Event()
    )
    device.assert_original()
    saved = engine.library_changes.save(review, Event())
    assert saved.active.library.tracks[:-1] == original_tracks
    for path, data in thumbnails.items():
        assert (device.root / path).read_bytes().startswith(data)
    assert saved.active.library.tracks[-1].artwork_id
    added_location = saved.active.library.tracks[-1].metadata.location
    engine.restore_last(Event())
    device.assert_original()
    assert not (device.root / added_location).exists()


def test_playlist_only_save_maps_queued_new_playlist_parent_before_reprepare(
    connected: tuple[Device, ClassicDropEngine], tmp_path: Path
) -> None:
    _device, engine = connected
    entries = engine.preview((media_file(tmp_path),), Event())
    session = PlaylistSession(engine.active.library)
    draft_parent = _create(session, "Saved parent", PlaylistKind.FOLDER)
    state = ImportQueueState(
        "queued",
        entries,
        ImportDestination(new_name="Imported child", parent_id=draft_parent),
        source=engine.active,
    )
    engine.library_changes.bind_queue(lambda: state)
    saved = engine.library_changes.save(
        engine.library_changes.prepare(session, (), ImportDestination(), Event()),
        Event(),
    )
    persistent_parent = dict(saved.playlist_ids)[draft_parent]
    carryover = saved.queue_carryover
    assert carryover is not None and carryover.destination is not None
    assert not carryover.requires_reselection
    assert carryover.destination.parent_id == persistent_parent > 0
    with pytest.raises(ValueError, match=r"preview|expired"):
        engine.validate_import_entries(entries, Event())
    fresh = engine.library_changes.reprepare_intents(carryover, Event())
    assert fresh[0].token != entries[0].token
    state = ImportQueueState(
        "prepared", fresh, carryover.destination, source=engine.active
    )
    imported = engine.library_changes.save(
        engine.library_changes.prepare(
            PlaylistSession(engine.active.library), fresh, state.destination, Event()
        ),
        Event(),
    )
    child = next(
        playlist
        for playlist in imported.active.library.playlists
        if playlist.name == "Imported child"
    )
    assert child.parent_id == persistent_parent
    assert child.track_ids == (imported.active.library.tracks[-1].track_id,)
