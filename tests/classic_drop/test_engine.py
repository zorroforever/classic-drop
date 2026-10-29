from dataclasses import replace
from threading import Event

import pytest

from classic_drop.engine import ClassicDropEngine, OperationCancelledError
from iOpenPod.app.display_text import SourceText, source_text
from iPodDB.iTunesDB.writer.signature import verify_hash58
from iPodDB.library import CoverFormat, CoverPixelFormat, IPodLibrary
from tests.classic_drop.test_media import media_file
from tests.iOpenPod.app.services.test_library_resources import build_device


@pytest.fixture
def connected(tmp_path):
    device = build_device(tmp_path)
    engine = ClassicDropEngine(
        data_directory=tmp_path / "host", coordinator=device.coordinator
    )
    engine.select(engine.discover()[0].id)
    try:
        yield device, engine
    finally:
        engine.close()


def test_selection_and_preview_do_not_write_the_device(connected, tmp_path):
    device, engine = connected
    before = {
        str(p.relative_to(device.root)): p.read_bytes()
        for p in device.root.rglob("*")
        if p.is_file()
    }
    entries = engine.preview((media_file(tmp_path),), Event())
    assert len(entries) == 1 and entries[0].selected
    assert {
        str(p.relative_to(device.root)): p.read_bytes()
        for p in device.root.rglob("*")
        if p.is_file()
    } == before


def test_preview_preserves_translatable_error_template(
    connected, tmp_path, monkeypatch
):
    _device, engine = connected
    source = media_file(tmp_path)

    def fail_preparation(*_args, **_kwargs):
        raise ValueError(source_text("File not found: {path}", path="missing.m4a"))

    monkeypatch.setattr("classic_drop.engine.prepare_song", fail_preparation)

    entry = engine.preview((source,), Event())[0]

    assert entry.detail == "File not found: missing.m4a"
    assert entry.detail.source == "File not found: {path}"


def test_append_preserves_old_library_and_writes_signed_covers(connected, tmp_path):
    device, engine = connected
    before = engine.active.library
    entries = engine.preview((media_file(tmp_path),), Event())
    result = engine.commit(entries, Event())
    assert result.added == 1 and result.recovery_path
    parsed = IPodLibrary((device.root / "iPod_Control/iTunes/iTunesDB").read_bytes())
    parsed = parsed.with_artwork(
        (device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes()
    )
    assert parsed.snapshot.tracks[:-1] == before.tracks
    assert parsed.snapshot.playlists[1:] == before.playlists[1:]
    added = parsed.snapshot.tracks[-1]
    assert added.title == "Chapter test" and added.artwork_id > 0
    assert verify_hash58(parsed.serialize().itunes, bytes.fromhex("000A270012345678"))
    for track in before.tracks:
        assert (device.root / track.metadata.location).read_bytes() == device.original[
            track.metadata.location
        ]
    for fmt in engine.active.profile.capabilities.artwork.cover_formats:
        read = parsed.artwork_read(
            added.artwork_id,
            (
                CoverFormat(
                    fmt.format_id,
                    fmt.width,
                    fmt.height,
                    fmt.row_bytes,
                    CoverPixelFormat(fmt.pixel_format.value),
                ),
            ),
            fmt.width,
        )
        assert read is not None
        data = (device.root / read.relative_path).read_bytes()
        pixels = read.decode(data[read.offset : read.offset + read.length])
        assert len(set(pixels.rgb888)) > 1


def test_repeat_import_is_verified_against_current_library(connected, tmp_path):
    _device, engine = connected
    source = media_file(tmp_path)
    engine.commit(engine.preview((source,), Event()), Event())
    again = engine.preview((source,), Event())
    assert len(again) == 1 and not again[0].selected
    assert again[0].status == "confirmed_duplicate"


def test_batch_duplicate_is_not_added_twice(connected, tmp_path):
    _device, engine = connected
    source = media_file(tmp_path)
    duplicate = tmp_path / "copy.m4a"
    duplicate.write_bytes(source.read_bytes())
    entries = engine.preview((source, duplicate), Event())
    assert sum(e.selected for e in entries) == 1
    assert entries[1].status == "confirmed_duplicate"


def test_duplicates_added_in_later_batches_are_detected(connected, tmp_path):
    _device, engine = connected
    source = media_file(tmp_path)
    duplicate = tmp_path / "later-copy.m4a"
    duplicate.write_bytes(source.read_bytes())

    first_batch = engine.preview((source,), Event())
    combined = engine.preview((source, duplicate), Event())

    assert len(combined) == 2
    assert combined[0].token == first_batch[0].token
    assert combined[1].status == "confirmed_duplicate"
    assert not combined[1].selected


def test_matching_library_content_is_verified_from_device(connected, tmp_path):
    device, engine = connected
    source = media_file(tmp_path)
    engine.commit(engine.preview((source,), Event()), Event())
    duplicate = tmp_path / "same-content-different-name.m4a"
    duplicate.write_bytes(source.read_bytes())

    entry = engine.preview((duplicate,), Event())[0]

    assert entry.status == "confirmed_duplicate"
    assert not entry.selected
    assert "SHA-256" in entry.detail
    assert device.root.joinpath(
        engine.active.library.tracks[-1].metadata.location
    ).exists()


def test_history_receipt_with_changed_device_content_is_not_confirmed(
    connected, tmp_path
):
    device, engine = connected
    source = media_file(tmp_path)
    engine.commit(engine.preview((source,), Event()), Event())
    target = device.root / engine.active.library.tracks[-1].metadata.location
    contents = target.read_bytes()
    target.write_bytes(bytes([contents[0] ^ 1]) + contents[1:])

    entry = engine.preview((source,), Event())[0]

    assert entry.status == "history_match"
    assert not entry.selected
    assert "device content differs" in entry.detail


def test_changed_source_cannot_publish_library(connected, tmp_path):
    device, engine = connected
    source = media_file(tmp_path)
    entries = engine.preview((source,), Event())
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError) as captured:
        engine.commit(entries, Event())
    message = captured.value.args[0]
    assert isinstance(message, SourceText)
    assert message.source == "File changed; preview it again: {name}"
    assert message.parameters == (("name", source.name),)
    device.assert_original()


def test_cancellation_leaves_original_library(connected, tmp_path):
    device, engine = connected
    entries = engine.preview((media_file(tmp_path),), Event())
    cancelled = Event()
    cancelled.set()
    with pytest.raises(OperationCancelledError, match=r"cancel|取消"):
        engine.commit(entries, cancelled)
    device.assert_original()


def test_restore_last_import_recovers_previous_bytes(connected, tmp_path):
    device, engine = connected
    entries = engine.preview((media_file(tmp_path),), Event())
    result = engine.commit(entries, Event())
    added_path = engine.active.library.tracks[-1].metadata.location
    engine.restore_last(Event())
    device.assert_original()
    assert not (device.root / added_path).exists()
    assert result.recovery_path


def test_successive_imports_remain_individually_recoverable(connected, tmp_path):
    device, engine = connected
    first_source = media_file(tmp_path, "chapters-cover.m4a")
    second_source = media_file(tmp_path, "tone.m4a")
    original = engine.active.library

    engine.commit(engine.preview((first_source,), Event()), Event())
    after_first = engine.active.library
    engine.commit(engine.preview((second_source,), Event()), Event())

    engine.restore_last(Event())
    assert engine.active.library == after_first

    engine.restore_last(Event())
    assert engine.active.library == original
    device.assert_original()


def test_user_edits_apply_only_to_new_tracks(connected, tmp_path):
    _device, engine = connected
    before = engine.active.library.tracks
    entries = engine.preview((media_file(tmp_path),), Event())
    entry = replace(entries[0], title="夜曲", album_artist="专辑艺人", disc_number=2)
    engine.commit((entry,), Event())
    assert engine.active.library.tracks[:-1] == before
    assert engine.active.library.tracks[-1].title == "夜曲"
    assert engine.active.library.tracks[-1].metadata.disc_number == 2


def test_non_classic_is_rejected_before_selection(tmp_path):
    device = build_device(tmp_path, model="M9802")
    engine = ClassicDropEngine(
        data_directory=tmp_path / "host", coordinator=device.coordinator
    )
    try:
        with pytest.raises(ValueError, match="Classic"):
            engine.select(device.coordinator.discovery.candidates[0].id)
    finally:
        engine.close()
