"""Composer names need not have one historical native identity."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source
from tests.iPodDB.library.test_media_lifecycle import prepared_media

from iPodDB.device_time import TimeConversion
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, Track, _write_preparation
from iPodDB.library._reconcile import reconcile
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library._track_writing import edit_text
from iPodDB.library.writing import IdentityMapping, WriteIssue, WriteResources
from iPodDB.shared.chunk import DatabaseDocument


def composer_source(second_identity: int = 17) -> IPodLibrary:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    second = document.find_chunks(MhitHeader)[1]
    changed = replace(
        second.chunk, header=replace(second.chunk.header, composer_id=second_identity)
    )
    document = document.replace_chunk(
        second, edit_text(changed, MhodType.COMPOSER, "COMPOSER")
    )
    return IPodLibrary(write_iTunesDB(document))


def incoming(source: IPodLibrary, identity: int, composer: str) -> Track:
    first = source.snapshot.tracks[0]
    return replace(
        first,
        track_id=identity,
        title=f"Incoming {identity}",
        size_bytes=5,
        metadata=replace(
            first.metadata,
            location=f"iPod_Control/Music/F00/new{-identity}.m4a",
            composer=composer,
            sample_rate_hz=44100,
            file_format="AAC audio file",
        ),
        ipod=None,
    )


@pytest.mark.parametrize("rename", [False, True])
def test_ambiguous_historical_composer_names_get_a_fresh_identity(
    rename: bool,
) -> None:
    source = composer_source()
    original = source.serialize().itunes
    unchanged = source.prepare(source.analyze(source.begin_draft()))
    assert unchanged.prepared is not None, unchanged.issues
    assert unchanged.prepared.itunes == original
    initial = incoming(source, -1, "Other composer")
    if rename:
        result = source.prepare(
            source.analyze(
                source.begin_draft(
                    replace(source.snapshot, tracks=(*source.snapshot.tracks, initial))
                )
            ),
            WriteResources(
                media=(prepared_media(initial, b"audio"),),
                pending_playback_sidecars=False,
            ),
        )
        assert result.prepared is not None, result.issues
        source = IPodLibrary(result.prepared.itunes)
        desired = replace(
            source.snapshot,
            tracks=(
                *source.snapshot.tracks[:2],
                replace(
                    source.snapshot.tracks[2],
                    metadata=replace(
                        source.snapshot.tracks[2].metadata, composer="Composer"
                    ),
                ),
            ),
        )
        resources = WriteResources()
    else:
        added = (incoming(source, -1, "Composer"), incoming(source, -2, "composer"))
        desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, *added))
        resources = WriteResources(
            media=tuple(prepared_media(t, b"audio") for t in added),
            pending_playback_sidecars=False,
        )
    before = source.serialize().itunes
    result = source.prepare(source.analyze(source.begin_draft(desired)), resources)
    assert result.prepared is not None, result.issues
    assert source.serialize().itunes == before
    after = IPodLibrary(result.prepared.itunes)
    assert after.snapshot.tracks[:2] == source.snapshot.tracks[:2]
    old_ids = {t.ipod.composer_id for t in source.snapshot.tracks if t.ipod}
    new_ids = {t.ipod.composer_id for t in after.snapshot.tracks[2:] if t.ipod}
    assert len(new_ids) == 1
    assert new_ids.isdisjoint(old_ids | {0, 5, 6, 8, 9})
    assert after.serialize().itunes == result.prepared.itunes


def test_import_reuses_a_unique_retained_composer_identity() -> None:
    source = browse_source()
    added = incoming(source, -1, "composer")
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, added))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(
            media=(prepared_media(added, b"audio"),), pending_playback_sidecars=False
        ),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[-1].ipod is not None
    assert result.prepared.snapshot.tracks[-1].ipod.composer_id == 7


def test_delete_and_import_cannot_recycle_a_historical_composer_candidate() -> None:
    source = composer_source(second_identity=10)
    added = incoming(source, -1, "Composer")
    desired = replace(
        source.snapshot,
        tracks=(source.snapshot.tracks[0], added),
        playlists=tuple(
            replace(p, entries=tuple(e for e in p.entries if e.track_id != 2))
            for p in source.snapshot.playlists
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True)),
        WriteResources(
            media=(prepared_media(added, b"audio"),), pending_playback_sidecars=False
        ),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[-1].ipod is not None
    assert result.prepared.snapshot.tracks[-1].ipod.composer_id not in {0, 7, 10}


@pytest.mark.parametrize("wrong_id", [0, 7, 17, 5, 999])
def test_verifier_rejects_invalid_or_split_new_composer_identity(
    monkeypatch: pytest.MonkeyPatch, wrong_id: int
) -> None:
    source = composer_source()
    added = (incoming(source, -1, "Composer"), incoming(source, -2, "composer"))
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, *added))

    def corrupt(
        document: DatabaseDocument[MhbdHeader],
        resolved: ResolvedWrite,
        resources: WriteResources,
        issues: list[WriteIssue],
        device_time: TimeConversion = 0,
    ) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
        candidate, mappings = reconcile(
            document, resolved, resources, issues, device_time
        )
        selection = candidate.find_chunks(MhitHeader)[-1]
        return candidate.replace_chunk(
            selection,
            replace(
                selection.chunk,
                header=replace(selection.chunk.header, composer_id=wrong_id),
            ),
        ), mappings

    monkeypatch.setattr(_write_preparation, "reconcile", corrupt)
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(
            media=tuple(prepared_media(t, b"audio") for t in added),
            pending_playback_sidecars=False,
        ),
    )
    assert result.prepared is None
    assert any(i.code == "verification.browse_composer_identity" for i in result.issues)
