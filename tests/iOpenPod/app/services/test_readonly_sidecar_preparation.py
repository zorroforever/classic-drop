"""Read-only sidecar projection bound to the exact issued Library Review."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iPodDB.sidecars.test_sidecar_readers import counts, otg

from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    LibraryReview,
    WriteProgress,
)
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistEntry


@pytest.fixture
def device(tmp_path: Path) -> Iterator[Device]:
    fixture = build_device(tmp_path)
    try:
        yield fixture
    finally:
        fixture.coordinator.close()


def prepare(
    device: Device, snapshot: LibrarySnapshot, *, delete: bool = False
) -> LibraryReview:
    return device.coordinator.prepare_library(
        LibraryPreparationRequest(
            snapshot,
            device.active,
            1,
            1,
            delete_omissions=delete,
            reconcile_sidecars=True,
        ),
        lambda _: None,
        Event(),
    )


def device_bytes(device: Device) -> dict[str, bytes]:
    return {
        path.relative_to(device.root).as_posix(): path.read_bytes()
        for path in device.root.rglob("*")
        if path.is_file()
    }


def playlist_edit(snapshot: LibrarySnapshot) -> LibrarySnapshot:
    first, *rest = snapshot.playlists
    return replace(
        snapshot,
        playlists=(
            replace(first, name="Reviewed name", entries=first.entries[::-1]),
            *rest,
        ),
    )


def test_preparation_retains_fresh_history_and_otg_without_changing_device_or_active(
    device: Device,
) -> None:
    # Replacing the complete old Snapshot would lose both playback and new OTG.
    active = device.active
    directory = device.root / "iPod_Control/iTunes"
    (directory / "Play Counts").write_bytes(counts(((3, 0, 500),), width=12))
    (directory / "OTGPlaylistInfo").write_bytes(otg((1, 0, 1)))
    (directory / "Play Counts.bak").write_bytes(b"previous backup")
    before = device_bytes(device)

    review = prepare(device, playlist_edit(active.library))

    assert review.result.prepared is not None, review.result.issues
    projected = review.result.prepared.snapshot
    assert projected.tracks[0].play_count == 3
    assert projected.tracks[0].metadata.unscrobbled_play_count == 3
    assert projected.tracks[0].metadata.bookmark_time_ms == 500
    assert projected.playlists[0].name == "Reviewed name"
    assert (
        projected.playlists[0].track_ids == active.library.playlists[0].track_ids[::-1]
    )
    assert projected.playlists[-1].name == "On-The-Go 1"
    assert projected.playlists[-1].track_ids == (2, 1, 2)
    assert device_bytes(device) == before
    assert device.active is active
    assert active.library.tracks[0].play_count == 0
    assert active.library.playlists[0].name == "Playlist"


def test_explicit_metadata_fields_merge_without_overwriting_sidecar_metadata(
    device: Device,
) -> None:
    # A shallow Track/metadata replacement would erase bookmark and play facts.
    original = device.active.library
    first, second = original.tracks
    desired = replace(
        original,
        tracks=(
            replace(
                first,
                title="Edited title",
                metadata=replace(first.metadata, comment="Edited comment"),
            ),
            second,
        ),
    )
    path = device.root / "iPod_Control/iTunes/Play Counts"
    path.write_bytes(counts(((3, 0, 500),), width=12))

    review = prepare(device, desired)

    assert review.result.prepared is not None, review.result.issues
    first, second = review.result.prepared.snapshot.tracks
    assert first.title == "Edited title"
    assert first.metadata.comment == "Edited comment"
    assert first.play_count == 3
    assert first.metadata.bookmark_time_ms == 500
    assert first.metadata.unscrobbled_play_count == 3
    assert second == original.tracks[1]


def test_only_exact_review_can_publish_history_playlist_and_sidecars_together(
    device: Device,
) -> None:
    directory = device.root / "iPod_Control/iTunes"
    data = counts(((3, 0, 500),), width=12)
    (directory / "Play Counts").write_bytes(data)
    (directory / "Play Counts.bak").write_bytes(b"previous backup")
    original = device_bytes(device)
    review = prepare(device, playlist_edit(device.active.library))
    assert review.result.prepared is not None, review.result.issues
    assert {(change.path, change.action) for change in review.file_changes} >= {
        ("iPod_Control/iTunes/iTunesDB", "write"),
        ("iPod_Control/iTunes/Play Counts.bak", "write"),
        ("iPod_Control/iTunes/Play Counts", "remove"),
    }

    copied = device.save(replace(review))
    assert copied.active is None
    assert copied.issues[0].code == "save.stale"
    assert device_bytes(device) == original
    saved = device.save(review)

    assert saved.active is not None, saved.issues
    assert saved.active.library == review.result.prepared.snapshot
    assert saved.active.library.tracks[0].play_count == 3
    assert saved.active.library.playlists[0].name == "Reviewed name"
    assert not (directory / "Play Counts").exists()
    assert (directory / "Play Counts.bak").read_bytes() == data
    device.restore(saved.recovery_path)
    assert (directory / "Play Counts").read_bytes() == data
    assert (directory / "Play Counts.bak").read_bytes() == b"previous backup"


@pytest.mark.parametrize("phase", ["after_review", "save.storage.prepared"])
@pytest.mark.parametrize(
    ("pending", "mutation"),
    [(False, "new"), (True, "changed"), (True, "missing"), (True, "new")],
)
def test_playlist_review_rejects_changed_or_new_sidecar_inventory(
    device: Device, phase: str, mutation: str, pending: bool
) -> None:
    # Without the request-level inventory gate a Playlist-only edit misses new files.
    directory = device.root / "iPod_Control/iTunes"
    path = directory / "Play Counts"
    if pending:
        path.write_bytes(counts(((3, 0, 0),), width=12))
    review = prepare(device, playlist_edit(device.active.library))
    assert review.result.prepared is not None, review.result.issues

    def mutate() -> None:
        if mutation == "changed":
            path.write_bytes(counts(((7, 0, 0),), width=12))
        elif mutation == "missing":
            path.unlink()
        else:
            (directory / "OTGPlaylistInfo_9").write_bytes(otg((0,)))

    if phase == "after_review":
        mutate()

    def progress(event: WriteProgress) -> None:
        if event.phase == phase:
            mutate()

    saved = device.save(review, progress)

    assert saved.active is None
    assert saved.issues[0].code in ("save.source_unavailable", "save.failed")
    device.assert_original()
    assert not (directory / "Play Counts.bak").exists()
    if mutation == "changed":
        assert path.read_bytes() == counts(((7, 0, 0),), width=12)
    elif mutation == "missing":
        assert not path.exists()
    else:
        assert (directory / "OTGPlaylistInfo_9").read_bytes() == otg((0,))


@pytest.mark.parametrize("mutation", ["changed", "new"])
def test_sidecar_change_expires_review_even_if_evidence_is_restored(
    device: Device, mutation: str
) -> None:
    # A failed evidence check must revoke authority, not permit a later retry.
    directory = device.root / "iPod_Control/iTunes"
    path = directory / "Play Counts"
    original = counts(((3, 0, 0),), width=12)
    path.write_bytes(original)
    review = prepare(device, playlist_edit(device.active.library))
    assert review.result.prepared is not None, review.result.issues
    if mutation == "changed":
        path.write_bytes(counts(((7, 0, 0),), width=12))
    else:
        (directory / "OTGPlaylistInfo").write_bytes(otg((0,)))

    assert device.save(review).active is None
    if mutation == "changed":
        path.write_bytes(original)
    else:
        (directory / "OTGPlaylistInfo").unlink()
    retried = device.save(review)

    assert retried.active is None
    assert retried.issues[0].code == "save.stale"
    assert path.read_bytes() == original
    device.assert_original()


@pytest.mark.parametrize("conflict", ["rating", "bookmark", "playlist_id", "malformed"])
def test_ambiguous_sidecar_overlay_blocks_review_and_preserves_host_intent(
    device: Device, conflict: str
) -> None:
    original = device.active.library
    desired = playlist_edit(original)
    directory = device.root / "iPod_Control/iTunes"
    if conflict == "playlist_id":
        desired = replace(
            desired, playlists=(*desired.playlists, Playlist(-1, "Host addition"))
        )
        (directory / "OTGPlaylistInfo").write_bytes(otg((0,)))
    else:
        first, second = desired.tracks
        if conflict == "rating":
            first = replace(first, rating=100)
        elif conflict == "bookmark":
            first = replace(
                first, metadata=replace(first.metadata, bookmark_time_ms=900)
            )
        desired = replace(desired, tracks=(first, second))
        (directory / "Play Counts").write_bytes(
            b"malformed history"
            if conflict == "malformed"
            else counts(((3, 0, 500, 80),), width=16)
        )
    before = device_bytes(device)

    review = prepare(device, desired)

    assert review.result.prepared is None
    assert review.result.issues
    assert device_bytes(device) == before
    assert device.active.library is original
    assert desired.playlists[0].name == "Reviewed name"


def test_playlist_omission_does_not_drop_new_otg_or_other_tracks(
    device: Device,
) -> None:
    original = device.active.library
    (device.root / "iPod_Control/iTunes/OTGPlaylistInfo").write_bytes(otg((1, 1, 0)))

    review = prepare(device, replace(original, playlists=()), delete=True)

    assert review.result.prepared is not None, review.result.issues
    assert review.result.prepared.snapshot.tracks == original.tracks
    assert len(review.result.prepared.snapshot.playlists) == 1
    assert review.result.prepared.snapshot.playlists[0].name == "On-The-Go 1"
    assert review.result.prepared.snapshot.playlists[0].track_ids == (2, 2, 1)


def test_nonconflicting_new_playlist_keeps_stable_references_beside_otg(
    device: Device,
) -> None:
    original = device.active.library
    (device.root / "iPod_Control/iTunes/OTGPlaylistInfo").write_bytes(otg((1,)))
    desired = replace(
        original,
        playlists=(
            *original.playlists,
            Playlist(-20, "Host addition", entries=(PlaylistEntry("host:1", 1),)),
        ),
    )

    review = prepare(device, desired)

    assert review.result.prepared is not None, review.result.issues
    playlists = review.result.prepared.snapshot.playlists
    assert [(p.name, p.track_ids) for p in playlists] == [
        ("Playlist", original.playlists[0].track_ids),
        ("Host addition", (1,)),
        ("On-The-Go 1", (2,)),
    ]
