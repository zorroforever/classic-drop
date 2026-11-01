"""Playlist drafts preserve occurrence identity and reject incomplete edits."""

from dataclasses import replace

import pytest

from classic_drop import playlists as drafts
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistEntry, Track
from iPodDB.library.playlists import (
    PlaylistKind,
    PlaylistSortOrder,
    SmartField,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    UnsupportedSmartRule,
)


def library() -> LibrarySnapshot:
    return LibrarySnapshot(
        tracks=(
            Track(1, "Zulu", "Artist", "Album", 1000),
            Track(2, "Alpha", "Artist", "Album", 2000),
        ),
        playlists=(
            Playlist(
                10,
                "Same",
                entries=(
                    PlaylistEntry("a", 1, 0),
                    PlaylistEntry("b", 1, 1),
                    PlaylistEntry("c", 2, 2),
                ),
            ),
        ),
    )


def apply(
    session: drafts.PlaylistSession,
    action: str,
    *,
    playlist_id: int | None = None,
    name: str | None = None,
    parent_id: int | None = None,
    kind: PlaylistKind = PlaylistKind.PLAYLIST,
    entry_ids: tuple[str, ...] = (),
    track_ids: tuple[int, ...] = (),
    sort_order: PlaylistSortOrder | None = None,
    smart: SmartPlaylist | None = None,
    allow_repeat: bool = False,
) -> drafts.PlaylistEditResult:
    return session.edit(
        drafts.PlaylistEdit(
            drafts.PlaylistAction(action),
            playlist_id,
            name,
            parent_id,
            kind,
            entry_ids,
            track_ids,
            sort_order,
            smart,
            allow_repeat=allow_repeat,
        ),
        expected_revision=session.revision,
    )


def test_create_all_kinds_preserves_same_names_and_trims_names() -> None:
    session = drafts.PlaylistSession(library())
    for kind in PlaylistKind:
        result = apply(session, "create", name=" Same ", kind=kind)
        assert result.playlist is not None
        assert result.playlist.name == "Same"
        assert result.playlist.kind is kind
    assert len({item.playlist_id for item in session.snapshot.playlists}) == 4
    assert library().playlists == session.original_snapshot.playlists


def test_append_skips_duplicates_by_default_and_reports_count() -> None:
    session = drafts.PlaylistSession(library())
    result = apply(session, "append", playlist_id=10, track_ids=(1, 2, 2))
    assert result.skipped_duplicates == 3
    assert session.snapshot == library()
    result = apply(session, "append", playlist_id=10, track_ids=(1,), allow_repeat=True)
    assert result.playlist is not None
    assert result.playlist.track_ids == (1, 1, 2, 1)
    assert result.playlist.entries[:3] == library().playlists[0].entries
    assert len({item.entry_id for item in result.playlist.entries}) == 4


def test_remove_and_move_use_exact_duplicate_entry() -> None:
    session = drafts.PlaylistSession(library())
    apply(session, "move_entries_down", playlist_id=10, entry_ids=("a",))
    assert tuple(e.entry_id for e in session.snapshot.playlists[0].entries) == (
        "b",
        "a",
        "c",
    )
    apply(session, "remove_entries", playlist_id=10, entry_ids=("a",))
    assert tuple(e.entry_id for e in session.snapshot.playlists[0].entries) == (
        "b",
        "c",
    )
    assert session.snapshot.tracks == library().tracks


def test_invalid_append_is_atomic_and_does_not_consume_revision() -> None:
    session = drafts.PlaylistSession(library())
    revision = session.revision
    with pytest.raises(ValueError):
        apply(session, "append", playlist_id=10, track_ids=(2, 999), allow_repeat=True)
    assert session.snapshot == library()
    assert session.revision == revision
    assert not session.can_undo


def test_undo_redo_discard_invalidate_stale_revisions_without_reusing_ids() -> None:
    session = drafts.PlaylistSession(library())
    initial = session.revision
    created = apply(session, "create", name="New").playlist
    assert created is not None
    changed = session.revision
    session.undo(expected_revision=changed)
    assert session.snapshot == library()
    assert session.revision not in (initial, changed)
    with pytest.raises(ValueError):
        session.redo(expected_revision=changed)
    session.redo(expected_revision=session.revision)
    assert session.snapshot.playlists[-1] == created
    session.undo(expected_revision=session.revision)
    other = apply(session, "create", name="Other").playlist
    assert other is not None and other.playlist_id != created.playlist_id
    assert not session.can_redo
    session.discard(expected_revision=session.revision)
    assert not session.dirty and not session.can_undo and not session.can_redo


def test_recursive_folder_moves_reject_cycles_and_delete_descendants_only() -> None:
    session = drafts.PlaylistSession(library())
    root = apply(session, "create", name="Root", kind=PlaylistKind.FOLDER).playlist
    assert root is not None
    child = apply(
        session,
        "create",
        name="Child",
        kind=PlaylistKind.FOLDER,
        parent_id=root.playlist_id,
    ).playlist
    assert child is not None
    apply(session, "move", playlist_id=10, parent_id=child.playlist_id)
    before = session.snapshot
    with pytest.raises(ValueError):
        apply(
            session, "move", playlist_id=root.playlist_id, parent_id=child.playlist_id
        )
    assert session.snapshot == before
    assert {p.playlist_id for p in session.deletion_impact(root.playlist_id)} == {
        10,
        root.playlist_id,
        child.playlist_id,
    }
    apply(session, "delete", playlist_id=root.playlist_id)
    assert session.snapshot.playlists == ()
    assert session.snapshot.tracks == library().tracks


@pytest.mark.parametrize(
    "action",
    [
        "update",
        "move",
        "delete",
        "append",
        "remove_entries",
        "copy_regular",
        "evaluate",
    ],
)
def test_system_managed_targets_reject_all_edits(action: str) -> None:
    original = replace(
        library(), playlists=(replace(library().playlists[0], system_managed=True),)
    )
    session = drafts.PlaylistSession(original)
    with pytest.raises(ValueError, match="managed"):
        apply(
            session,
            action,
            playlist_id=10,
            name="Changed",
            track_ids=(2,),
            entry_ids=("a",),
        )
    assert session.snapshot == original


def test_delete_rejects_protected_descendant() -> None:
    source = replace(
        library(),
        playlists=(
            Playlist(20, "Folder", kind=PlaylistKind.FOLDER),
            replace(library().playlists[0], parent_id=20, system_managed=True),
        ),
    )
    session = drafts.PlaylistSession(source)
    with pytest.raises(ValueError, match="managed"):
        apply(session, "delete", playlist_id=20)
    assert session.snapshot == source


def test_delete_reports_smart_dependents_of_descendants() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.PLAYLIST, SmartOperator.IS, SmartPlaylistReference(10)
                ),
            )
        )
    )
    source = replace(
        library(),
        playlists=(
            Playlist(20, "Folder", kind=PlaylistKind.FOLDER),
            replace(library().playlists[0], parent_id=20),
            Playlist(30, "Dependent", kind=PlaylistKind.SMART, smart=smart),
        ),
    )
    session = drafts.PlaylistSession(source)
    with pytest.raises(drafts.PlaylistDependencyError) as error:
        apply(session, "delete", playlist_id=20)
    assert error.value.dependent_ids == (30,)
    assert "Dependent" in str(error.value)
    assert session.snapshot == source


def test_unsupported_smart_is_preserved_by_safe_edits_but_blocks_deletion() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(rules=(UnsupportedSmartRule("opaque native rule"),)),
        editable=False,
    )
    imported = Playlist(
        30,
        "Imported",
        kind=PlaylistKind.SMART,
        smart=smart,
        entries=(PlaylistEntry("saved", 2),),
    )
    session = drafts.PlaylistSession(
        replace(library(), playlists=(*library().playlists, imported))
    )
    apply(session, "update", playlist_id=30, name="Renamed")
    apply(session, "move", playlist_id=30)
    assert session.playlist(30).smart is smart
    assert session.playlist(30).entries == imported.entries
    copy = apply(session, "copy_regular", playlist_id=30, name="Copy").playlist
    assert copy is not None and copy.track_ids == (2,) and copy.smart is None
    with pytest.raises(ValueError):
        apply(session, "update", playlist_id=30, smart=SmartPlaylist())
    with pytest.raises(ValueError):
        apply(session, "evaluate", playlist_id=30)
    with pytest.raises(drafts.PlaylistDependencyError, match="Renamed"):
        apply(session, "delete", playlist_id=10)


def test_supported_smart_preview_is_pure_and_rule_application_updates_membership() -> (
    None
):
    session = drafts.PlaylistSession(library())
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.TITLE, SmartOperator.IS, "Alpha"),)
        )
    )
    revision = session.revision
    assert tuple(t.track_id for t in session.preview(smart, now=100)) == (2,)
    assert session.revision == revision and not session.dirty
    result = apply(
        session, "create", name="Smart", kind=PlaylistKind.SMART, smart=smart
    )
    assert result.playlist is not None and result.playlist.track_ids == (2,)
    with pytest.raises(ValueError):
        apply(
            session, "append", playlist_id=result.playlist.playlist_id, track_ids=(1,)
        )


def test_reorder_requires_complete_exact_entries_and_manual_sort() -> None:
    session = drafts.PlaylistSession(library())
    with pytest.raises(ValueError):
        apply(session, "reorder_entries", playlist_id=10, entry_ids=("b", "a"))
    apply(session, "reorder_entries", playlist_id=10, entry_ids=("c", "b", "a"))
    assert tuple(e.entry_id for e in session.playlist(10).entries) == ("c", "b", "a")
    apply(session, "update", playlist_id=10, sort_order=PlaylistSortOrder.TITLE)
    with pytest.raises(ValueError):
        apply(session, "reorder_entries", playlist_id=10, entry_ids=("c", "a", "b"))


def test_regular_copy_respects_explicit_default_sort_order() -> None:
    session = drafts.PlaylistSession(library())
    result = apply(
        session, "copy_regular", playlist_id=10, sort_order=PlaylistSortOrder.DEFAULT
    )
    assert result.playlist is not None
    assert result.playlist.sort_order is PlaylistSortOrder.DEFAULT


def test_persist_temporary_sort_switches_to_manual_in_one_undoable_edit() -> None:
    session = drafts.PlaylistSession(library())
    apply(session, "update", playlist_id=10, sort_order=PlaylistSortOrder.TITLE)
    before = session.snapshot
    apply(
        session,
        "reorder_entries",
        playlist_id=10,
        entry_ids=("c", "b", "a"),
        sort_order=PlaylistSortOrder.MANUAL,
    )
    assert session.playlist(10).sort_order is PlaylistSortOrder.MANUAL
    assert tuple(e.entry_id for e in session.playlist(10).entries) == ("c", "b", "a")
    session.undo(expected_revision=session.revision)
    assert session.snapshot == before


@pytest.mark.parametrize(
    ("entry_ids", "sort_order"),
    [
        (("c", "b"), PlaylistSortOrder.MANUAL),
        (("c", "b", "a"), PlaylistSortOrder.TITLE),
    ],
)
def test_persist_temporary_sort_rejects_partial_or_nonmanual_override(
    entry_ids: tuple[str, ...], sort_order: PlaylistSortOrder
) -> None:
    session = drafts.PlaylistSession(library())
    before = session.snapshot
    with pytest.raises(ValueError):
        apply(
            session,
            "reorder_entries",
            playlist_id=10,
            entry_ids=entry_ids,
            sort_order=sort_order,
        )
    assert session.snapshot == before
    assert not session.can_undo


@pytest.mark.parametrize("position", [None, 7])
def test_fully_skipped_append_preserves_retained_positions_and_history(
    position: int | None,
) -> None:
    original = replace(
        library(),
        playlists=(
            Playlist(10, "Retained", entries=(PlaylistEntry("saved", 1, position),)),
        ),
    )
    session = drafts.PlaylistSession(original)
    revision = session.revision
    result = apply(session, "append", playlist_id=10, track_ids=(1, 1))
    assert result.skipped_duplicates == 2
    assert session.snapshot == original
    assert session.revision == revision
    assert not session.dirty and not session.can_undo


@pytest.mark.parametrize("kind", [PlaylistKind.SMART, PlaylistKind.FOLDER])
def test_skipped_append_still_rejects_nonordinary_targets(kind: PlaylistKind) -> None:
    original = replace(
        library(),
        playlists=(
            Playlist(
                10,
                "Protected membership",
                kind=kind,
                entries=(PlaylistEntry("saved", 1, 7),),
            ),
        ),
    )
    session = drafts.PlaylistSession(original)
    with pytest.raises(ValueError, match="regular Playlists"):
        apply(session, "append", playlist_id=10, track_ids=(1,))
    assert session.snapshot == original and not session.can_undo
