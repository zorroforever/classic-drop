"""Native Playlist transport uses semantic sessions, never Track facets."""

import json
from dataclasses import asdict
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from classic_drop.native_backend import NativeBackend
from classic_drop.native_protocol import Request, Result
from classic_drop.playlists import PlaylistAction, PlaylistEdit
from iPodDB.library.playlists import PlaylistKind
from tests.classic_drop.test_engine import connected  # noqa: F401


@pytest.fixture
def backend(connected: Any) -> NativeBackend:  # noqa: F811
    return NativeBackend(connected[1])


def call(backend: NativeBackend, command: str, **kwargs: Any) -> Result:
    return backend.execute(
        Request("test", command, generation=backend.generation, **kwargs), Event()
    )


def draft(backend: NativeBackend) -> str:
    status = call(backend, "playlist_list").playlist_draft
    assert status is not None
    return status.revision


def test_typed_request_rejects_bad_playlist_payload_before_edit() -> None:
    raw: dict[str, Any] = {
        "id": "1",
        "command": "playlist_edit",
        "version": 1,
        "playlist_revision": "revision",
        "playlist_edit": {
            "action": "create",
            "name": "New",
            "track_ids": ["18446744073709551615"],
        },
    }
    request = Request.decode(json.dumps(raw).encode())
    assert request.playlist_edit is not None
    assert request.playlist_edit.track_ids == ((1 << 64) - 1,)
    raw["playlist_edit"]["track_ids"] = [123]
    with pytest.raises(ValueError):
        Request.decode(json.dumps(raw).encode())


def test_capability_edit_revision_and_duplicate_occurrence_pages(
    backend: NativeBackend,
) -> None:
    assert "playlists-v1" in call(backend, "hello").capabilities
    revision = draft(backend)
    track = backend.engine.active.library.tracks[0]
    created = call(
        backend,
        "playlist_edit",
        playlist_revision=revision,
        playlist_edit=PlaylistEdit(
            PlaylistAction.CREATE,
            name="Repeats",
            track_ids=(track.track_id, track.track_id),
            allow_repeat=True,
        ),
    )
    assert created.playlist_draft is not None and created.playlist_draft.dirty
    item = next(
        p for p in call(backend, "playlist_list").playlist_items if p.name == "Repeats"
    )
    first = call(backend, "playlist_entries", token=item.id, limit=1)
    second = call(backend, "playlist_entries", token=item.id, offset=1, limit=1)
    assert first.total == 2
    assert first.playlist_entries[0].track_id == second.playlist_entries[0].track_id
    assert first.playlist_entries[0].entry_id != second.playlist_entries[0].entry_id
    with pytest.raises(ValueError, match="draft changed"):
        call(backend, "playlist_undo", playlist_revision=revision)
    call(backend, "playlist_undo", playlist_revision=draft(backend))
    status = call(backend, "playlist_list").playlist_draft
    assert status is not None and not status.dirty


@pytest.mark.parametrize(
    "command", ["select", "eject", "restore", "prepare_delete", "delete", "commit"]
)
def test_unsaved_playlist_guard_precedes_other_mutations(
    backend: NativeBackend, command: str
) -> None:
    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Draft"),
    )
    with pytest.raises(ValueError, match="unsaved Playlist"):
        call(backend, command)


def test_atomic_chunk_upload_does_not_apply_partial_action(
    backend: NativeBackend,
) -> None:
    revision = draft(backend)
    started = call(
        backend,
        "playlist_edit_begin",
        playlist_revision=revision,
        playlist_edit=PlaylistEdit(
            PlaylistAction.CREATE, name="Chunked", allow_repeat=True
        ),
        batch_count=2,
    )
    token = started.batch_token
    track = str(backend.engine.active.library.tracks[0].track_id)
    call(
        backend,
        "playlist_edit_chunk",
        playlist_revision=revision,
        token=token,
        ids=(track,),
        source="tracks",
        offset=0,
    )
    status = call(backend, "playlist_list").playlist_draft
    assert status is not None and not status.dirty
    with pytest.raises(ValueError, match="chunk"):
        call(
            backend,
            "playlist_edit_chunk",
            playlist_revision=revision,
            token=token,
            ids=(track,),
            source="tracks",
            offset=2,
        )
    call(
        backend,
        "playlist_edit_chunk",
        playlist_revision=revision,
        token=token,
        ids=(track,),
        source="tracks",
        offset=1,
    )
    result = call(
        backend, "playlist_edit_finish", playlist_revision=revision, token=token
    )
    assert result.playlist_draft is not None and result.playlist_draft.dirty
    item = next(
        p for p in call(backend, "playlist_list").playlist_items if p.name == "Chunked"
    )
    assert item.entry_count == 2


def test_check_is_read_only_save_requires_current_issued_review(
    backend: NativeBackend,
    connected: Any,  # noqa: F811
) -> None:
    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Saved"),
    )
    root = connected[0].root
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    checked = call(backend, "playlist_prepare", playlist_revision=draft(backend))
    assert checked.playlist_review is not None
    assert before == {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    saved = call(
        backend,
        "playlist_save",
        playlist_revision=draft(backend),
        token=checked.playlist_review.token,
    )
    assert saved.playlist_draft is not None and not saved.playlist_draft.dirty
    assert any(p.name == "Saved" for p in backend.engine.active.library.playlists)
    assert saved.playlist_id_map
    json.dumps(asdict(saved))


def test_playlist_save_stale_after_queue_edit_and_draft_edit(
    backend: NativeBackend,
) -> None:
    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Draft"),
    )
    review = call(
        backend, "playlist_prepare", playlist_revision=draft(backend)
    ).playlist_review
    assert review is not None
    call(backend, "edit", revision=backend.revision)
    with pytest.raises(ValueError, match="Review expired"):
        call(
            backend,
            "playlist_save",
            playlist_revision=draft(backend),
            token=review.token,
        )
    reviewed = call(
        backend, "playlist_prepare", playlist_revision=draft(backend)
    ).playlist_review
    assert reviewed is not None
    old_revision = draft(backend)
    call(backend, "playlist_undo", playlist_revision=old_revision)
    with pytest.raises(ValueError, match="draft changed"):
        call(
            backend,
            "playlist_save",
            playlist_revision=old_revision,
            token=reviewed.token,
        )


def test_playlist_only_save_keeps_host_queue_visible_and_reprepares(
    backend: NativeBackend, tmp_path: Any
) -> None:
    from tests.classic_drop.test_media import media_file

    call(backend, "preview", paths=(str(media_file(tmp_path)),))
    original_token = next(iter(backend.entries))
    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Target"),
    )
    target = next(
        p for p in call(backend, "playlist_list").playlist_items if p.name == "Target"
    )
    from classic_drop.native_playlists import ImportDestinationDTO

    call(
        backend,
        "import_destination",
        playlist_revision=draft(backend),
        revision=backend.revision,
        destination=ImportDestinationDTO(playlist_ids=(target.id,)),
    )
    reviewed = call(
        backend, "playlist_prepare", playlist_revision=draft(backend)
    ).playlist_review
    assert reviewed is not None
    saved = call(
        backend, "playlist_save", playlist_revision=draft(backend), token=reviewed.token
    )
    assert saved.queue_needs_preparation
    assert saved.state.queue_count == 1
    assert call(backend, "queue").preview[0].path
    assert int(saved.destination.playlist_ids[0]) > 0
    assert not backend.entries
    prepared = call(
        backend,
        "queue_reprepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
    )
    assert not prepared.queue_needs_preparation and prepared.preview
    assert prepared.preview[0].token != original_token
    combined = call(
        backend,
        "playlist_prepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
        include_imports=True,
    ).playlist_review
    assert combined is not None and combined.added == 1
    call(
        backend, "playlist_save", playlist_revision=draft(backend), token=combined.token
    )
    assert backend.engine.active.library.playlists[-1].entries


def test_cancelled_and_incomplete_upload_never_mutates_draft(
    backend: NativeBackend,
) -> None:
    from classic_drop.engine import OperationCancelledError

    revision = draft(backend)
    begun = call(
        backend,
        "playlist_edit_begin",
        playlist_revision=revision,
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Not applied"),
        batch_count=1,
    )
    cancelled = Event()
    cancelled.set()
    with pytest.raises(OperationCancelledError):
        backend.execute(
            Request(
                "cancelled",
                "playlist_edit_finish",
                generation=backend.generation,
                playlist_revision=revision,
                token=begun.batch_token,
            ),
            cancelled,
        )
    assert draft(backend) == revision
    call(
        backend,
        "playlist_edit_cancel",
        playlist_revision=revision,
        token=begun.batch_token,
    )
    with pytest.raises(ValueError, match="upload expired"):
        call(
            backend,
            "playlist_edit_finish",
            playlist_revision=revision,
            token=begun.batch_token,
        )


def test_whole_rule_record_over_frame_budget_is_explicit_error(
    backend: NativeBackend,
) -> None:
    from iPodDB.library.playlists import (
        SmartField,
        SmartOperator,
        SmartPlaylist,
        SmartRule,
        SmartRuleGroup,
    )

    smart = SmartPlaylist(
        SmartRuleGroup(
            rules=(SmartRule(SmartField.TITLE, SmartOperator.CONTAINS, "x" * 850_000),)
        )
    )
    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(
            PlaylistAction.CREATE, name="Large", kind=PlaylistKind.SMART, smart=smart
        ),
    )
    with pytest.raises(ValueError, match="complete Playlist record"):
        call(
            backend,
            "playlist_list",
            offset=len(backend.playlist_adapter.current().snapshot.playlists) - 1,
        )


def test_reuse_choice_selects_duplicate_without_copy_authorization(
    backend: NativeBackend, tmp_path: Any
) -> None:
    from classic_drop.native_playlists import ExistingTrackDTO, ImportDestinationDTO
    from classic_drop.native_protocol import Edit
    from tests.classic_drop.test_media import media_file

    path = str(media_file(tmp_path))
    call(backend, "preview", paths=(path,))
    review = call(
        backend,
        "playlist_prepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
        include_imports=True,
    ).playlist_review
    assert review is not None
    call(backend, "playlist_save", playlist_revision=draft(backend), token=review.token)
    track_id = str(backend.engine.active.library.tracks[-1].track_id)
    rows = call(backend, "preview", paths=(path,)).preview
    assert rows[0].status == "confirmed_duplicate" and not rows[0].selected
    token = rows[0].token
    call(
        backend,
        "import_destination",
        playlist_revision=draft(backend),
        revision=backend.revision,
        destination=ImportDestinationDTO(new_name="Reused"),
        reuse=(ExistingTrackDTO(token, track_id),),
    )
    call(
        backend,
        "edit",
        revision=backend.revision,
        edits=(Edit(token, title=rows[0].title, selected=True),),
    )
    review = call(
        backend,
        "playlist_prepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
        include_imports=True,
    ).playlist_review
    assert review is not None and review.added == 0 and review.reused == 1


def test_legacy_commit_cannot_silently_drop_playlist_import_intent(
    backend: NativeBackend,
) -> None:
    from classic_drop.native_playlists import ImportDestinationDTO

    call(
        backend,
        "import_destination",
        playlist_revision=draft(backend),
        revision=backend.revision,
        destination=ImportDestinationDTO(new_name="Destination"),
    )
    with pytest.raises(ValueError, match="reviewed Playlist"):
        call(backend, "commit", revision=backend.revision)


def test_deeply_nested_invalid_json_is_a_rejected_request() -> None:
    with pytest.raises(ValueError):
        Request.decode(
            b'{"version":1,"id":"nested","command":"playlist_edit","playlist_edit":'
            + b"[" * 2000
            + b"]" * 2000
            + b"}"
        )


def test_smart_preview_pages_share_one_fixed_evaluation(
    backend: NativeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iPodDB.library.playlists import (
        SmartField,
        SmartOperator,
        SmartPlaylist,
        SmartRule,
        SmartRuleGroup,
    )

    smart = SmartPlaylist(
        SmartRuleGroup(rules=(SmartRule(SmartField.TITLE, SmartOperator.CONTAINS, ""),))
    )
    session = backend.playlist_adapter.current()
    preview = session.preview
    calls = []

    def observed(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return preview(*args, **kwargs)

    monkeypatch.setattr(session, "preview", observed)
    first = call(
        backend,
        "playlist_preview",
        playlist_revision=draft(backend),
        smart=smart,
        limit=1,
    )
    second = call(
        backend,
        "playlist_preview",
        playlist_revision=draft(backend),
        smart=smart,
        limit=1,
        offset=1,
    )
    assert first.total == second.total
    assert len(calls) == 1


def test_read_page_can_bind_existing_revision(backend: NativeBackend) -> None:
    revision = draft(backend)
    call(
        backend,
        "playlist_edit",
        playlist_revision=revision,
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Changed"),
    )
    with pytest.raises(ValueError, match="draft changed"):
        call(backend, "playlist_list", playlist_revision=revision)


def test_missing_carryover_destination_still_requires_choice_after_reprepare(
    backend: NativeBackend, tmp_path: Any
) -> None:
    from classic_drop.native_playlists import ImportDestinationDTO
    from tests.classic_drop.test_media import media_file

    call(backend, "preview", paths=(str(media_file(tmp_path)),))
    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Transient"),
    )
    target = next(
        p
        for p in call(backend, "playlist_list").playlist_items
        if p.name == "Transient"
    )
    call(
        backend,
        "import_destination",
        playlist_revision=draft(backend),
        revision=backend.revision,
        destination=ImportDestinationDTO(playlist_ids=(target.id,)),
    )
    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(PlaylistAction.DELETE, int(target.id)),
    )
    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Keep"),
    )
    review = call(
        backend, "playlist_prepare", playlist_revision=draft(backend)
    ).playlist_review
    assert review is not None
    saved = call(
        backend, "playlist_save", playlist_revision=draft(backend), token=review.token
    )
    assert saved.queue_requires_reselection
    prepared = call(
        backend,
        "queue_reprepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
    )
    assert prepared.queue_requires_reselection
    with pytest.raises(ValueError, match="destination"):
        call(
            backend,
            "playlist_prepare",
            playlist_revision=draft(backend),
            revision=backend.revision,
            include_imports=True,
        )
    call(
        backend,
        "import_destination",
        playlist_revision=draft(backend),
        revision=backend.revision,
        destination=ImportDestinationDTO(),
    )
    assert not call(backend, "queue").queue_requires_reselection


def test_discard_import_resets_batch_intent_and_preserves_playlist_draft(
    backend: NativeBackend,
) -> None:
    from classic_drop.native_playlists import ImportDestinationDTO

    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Keep draft"),
    )
    call(
        backend,
        "import_destination",
        playlist_revision=draft(backend),
        revision=backend.revision,
        destination=ImportDestinationDTO(new_name="Batch only"),
    )
    result = call(backend, "discard")
    assert result.destination == ImportDestinationDTO()
    assert result.playlist_draft is not None and result.playlist_draft.dirty


def test_action_upload_requires_complete_declared_selection(
    backend: NativeBackend,
) -> None:
    revision = draft(backend)
    begun = call(
        backend,
        "playlist_edit_begin",
        playlist_revision=revision,
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Whole"),
        batch_count=2,
    )
    track = str(backend.engine.active.library.tracks[0].track_id)
    call(
        backend,
        "playlist_edit_chunk",
        playlist_revision=revision,
        token=begun.batch_token,
        source="tracks",
        ids=(track,),
        offset=0,
    )
    with pytest.raises(ValueError, match="incomplete"):
        call(
            backend,
            "playlist_edit_finish",
            playlist_revision=revision,
            token=begun.batch_token,
        )
    assert draft(backend) == revision


def test_decoder_turns_extreme_json_recursion_into_validation_error() -> None:
    with pytest.raises(ValueError):
        Request.decode(
            b'{"version":1,"id":"nested","command":"playlist_edit","playlist_edit":'
            + b"[" * 100_000
            + b"]" * 100_000
            + b"}"
        )


def test_helper_reports_complete_oversized_playlist_response_without_truncation(
    backend: NativeBackend,
) -> None:
    import io
    from dataclasses import replace

    from classic_drop.native_helper import HelperServer
    from classic_drop.native_protocol import MAX_MESSAGE

    output = io.StringIO()
    server = HelperServer(output, None)
    result = call(backend, "playlist_list")
    item = result.playlist_items[0]
    oversized = replace(result, playlist_items=(replace(item, name="x" * MAX_MESSAGE),))
    server.emit("oversized", "result", result=oversized)
    raw = output.getvalue().encode()
    assert len(raw) <= MAX_MESSAGE
    response = json.loads(raw)
    assert response["event"] == "error" and response["code"] == "response_too_large"
    assert response["result"] is None


def test_declared_batch_size_requires_integer_json() -> None:
    for value in [True, "2", -1, 2.5]:
        raw = {
            "version": 1,
            "id": "size",
            "command": "playlist_edit_begin",
            "batch_count": value,
        }
        with pytest.raises(ValueError):
            Request.decode(json.dumps(raw).encode())


def test_queue_reorder_rejects_stale_or_incomplete_manifest_without_mutation(
    backend: NativeBackend, tmp_path: Any
) -> None:
    from tests.classic_drop.test_media import media_file

    first = media_file(tmp_path)
    second = tmp_path / "second.m4a"
    second.write_bytes(first.read_bytes())
    call(backend, "preview", paths=(str(first), str(second)))
    original = tuple(backend.entries)
    revision = backend.revision
    for manifest in (original[:1], (*original, original[0]), (original[0], "expired")):
        with pytest.raises(ValueError, match="complete import queue"):
            call(backend, "queue_reorder", revision=revision, ids=manifest)
        assert tuple(backend.entries) == original and backend.revision == revision
    with pytest.raises(ValueError, match="queue changed"):
        call(backend, "queue_reorder", revision="expired", ids=original[::-1])
    assert tuple(backend.entries) == original and backend.revision == revision


def test_queue_reorder_controls_combined_destination_and_invalidates_review(
    backend: NativeBackend, tmp_path: Any
) -> None:
    from classic_drop.native_playlists import ImportDestinationDTO
    from classic_drop.native_protocol import Edit
    from tests.classic_drop.test_media import media_file

    first = media_file(tmp_path)
    second = tmp_path / "second.m4a"
    second.write_bytes(first.read_bytes())
    call(backend, "preview", paths=(str(first), str(second)))
    tokens = tuple(backend.entries)
    call(
        backend,
        "edit",
        revision=backend.revision,
        edits=tuple(
            Edit(token, title=f"Song {index}", selected=True, allow_duplicate=True)
            for index, token in enumerate(tokens)
        ),
    )
    call(
        backend,
        "import_destination",
        playlist_revision=draft(backend),
        revision=backend.revision,
        destination=ImportDestinationDTO(new_name="Ordered"),
        allow_duplicates=tokens,
    )
    reviewed = call(
        backend,
        "playlist_prepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
        include_imports=True,
    ).playlist_review
    assert reviewed is not None
    revision = backend.revision
    result = call(backend, "queue_reorder", revision=revision, ids=tokens[::-1])
    assert tuple(row.token for row in result.preview) == tokens[::-1]
    assert backend.revision != revision
    with pytest.raises(ValueError, match="Review expired"):
        call(
            backend,
            "playlist_save",
            playlist_revision=draft(backend),
            token=reviewed.token,
        )
    reviewed = call(
        backend,
        "playlist_prepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
        include_imports=True,
    ).playlist_review
    assert reviewed is not None
    call(
        backend, "playlist_save", playlist_revision=draft(backend), token=reviewed.token
    )
    playlist = next(
        p for p in backend.engine.active.library.playlists if p.name == "Ordered"
    )
    titles = {t.track_id: t.title for t in backend.engine.active.library.tracks}
    assert tuple(titles[entry.track_id] for entry in playlist.entries) == (
        "Song 1",
        "Song 0",
    )


def test_queue_reorder_requires_repreparing_retained_host_intent(
    backend: NativeBackend, tmp_path: Any
) -> None:
    from tests.classic_drop.test_media import media_file

    first = media_file(tmp_path)
    second = tmp_path / "second.m4a"
    second.write_bytes(first.read_bytes())
    call(backend, "preview", paths=(str(first), str(second)))
    tokens = tuple(backend.entries)
    reordered = call(
        backend, "queue_reorder", revision=backend.revision, ids=tokens[::-1]
    )
    ordered_paths = tuple(row.path for row in reordered.preview)
    call(
        backend,
        "playlist_edit",
        playlist_revision=draft(backend),
        playlist_edit=PlaylistEdit(PlaylistAction.CREATE, name="Save only"),
    )
    reviewed = call(
        backend, "playlist_prepare", playlist_revision=draft(backend)
    ).playlist_review
    assert reviewed is not None
    call(
        backend, "playlist_save", playlist_revision=draft(backend), token=reviewed.token
    )
    with pytest.raises(ValueError, match="Prepare the retained Host queue"):
        call(backend, "queue_reorder", revision=backend.revision, ids=tokens)
    retained = call(backend, "queue")
    assert retained.state.queue_count == 2
    assert tuple(row.path for row in retained.preview) == ordered_paths
    prepared = call(
        backend,
        "queue_reprepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
    )
    assert tuple(row.path for row in prepared.preview) == ordered_paths


def test_preparing_added_files_retains_acknowledged_queue_order(
    backend: NativeBackend, tmp_path: Any
) -> None:
    from tests.classic_drop.test_media import media_file

    first = media_file(tmp_path)
    second = tmp_path / "second.m4a"
    second.write_bytes(first.read_bytes())
    third = tmp_path / "third.m4a"
    third.write_bytes(first.read_bytes())
    call(backend, "preview", paths=(str(first), str(second)))
    tokens = tuple(backend.entries)
    call(backend, "queue_reorder", revision=backend.revision, ids=tokens[::-1])
    added = call(backend, "preview", paths=(str(third),))
    assert tuple(row.token for row in added.preview[:2]) == tokens[::-1]
    assert added.preview[2].path == str(third)


@pytest.mark.parametrize("choice", ["reuse", "copy"])
def test_review_excludes_deselected_row_authority_and_keeps_choice_for_reselection(
    backend: NativeBackend, tmp_path: Path, choice: str
) -> None:
    from classic_drop.native_playlists import ExistingTrackDTO, ImportDestinationDTO
    from classic_drop.native_protocol import Edit
    from tests.classic_drop.test_media import media_file

    original = str(media_file(tmp_path))
    call(backend, "preview", paths=(original,))
    first_review = call(
        backend,
        "playlist_prepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
        include_imports=True,
    ).playlist_review
    assert first_review is not None
    call(
        backend,
        "playlist_save",
        playlist_revision=draft(backend),
        token=first_review.token,
    )
    prior_count = len(backend.engine.active.library.tracks)
    existing_id = str(backend.engine.active.library.tracks[-1].track_id)
    new_path = str(media_file(tmp_path, "tone.m4a"))
    rows = call(backend, "preview", paths=(original, new_path)).preview
    duplicate = next(row for row in rows if row.path == original)
    fresh = next(row for row in rows if row.path == new_path)
    assert duplicate.status == "confirmed_duplicate" and fresh.status == "new"
    call(
        backend,
        "import_destination",
        playlist_revision=draft(backend),
        revision=backend.revision,
        destination=ImportDestinationDTO(new_name="Only selected songs"),
        reuse=(ExistingTrackDTO(duplicate.token, existing_id),)
        if choice == "reuse"
        else (),
        allow_duplicates=(duplicate.token,) if choice == "copy" else (),
    )
    call(
        backend,
        "edit",
        revision=backend.revision,
        edits=(
            Edit(
                duplicate.token,
                title=duplicate.title,
                selected=True,
                allow_duplicate=choice == "copy",
            ),
        ),
    )
    call(
        backend,
        "edit",
        revision=backend.revision,
        edits=(
            Edit(
                duplicate.token,
                title=duplicate.title,
                selected=False,
                allow_duplicate=choice == "copy",
            ),
        ),
    )
    reviewed = call(
        backend,
        "playlist_prepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
        include_imports=True,
    ).playlist_review
    assert reviewed is not None and reviewed.added == 1 and reviewed.reused == 0
    if choice == "reuse":
        assert backend.playlist_adapter.reuse == (
            ExistingTrackDTO(duplicate.token, existing_id),
        )
    else:
        assert duplicate.token in backend.playlist_adapter.allow_duplicates
    # The retained row choice becomes active only after explicit reselection.
    call(
        backend,
        "edit",
        revision=backend.revision,
        edits=(
            Edit(
                duplicate.token,
                title=duplicate.title,
                selected=True,
                allow_duplicate=choice == "copy",
            ),
        ),
    )
    reselected = call(
        backend,
        "playlist_prepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
        include_imports=True,
    ).playlist_review
    assert reselected is not None
    assert (reselected.added, reselected.reused) == (
        (1, 1) if choice == "reuse" else (2, 0)
    )
    call(
        backend,
        "edit",
        revision=backend.revision,
        edits=(
            Edit(
                duplicate.token,
                title=duplicate.title,
                selected=False,
                allow_duplicate=choice == "copy",
            ),
        ),
    )
    reviewed = call(
        backend,
        "playlist_prepare",
        playlist_revision=draft(backend),
        revision=backend.revision,
        include_imports=True,
    ).playlist_review
    assert reviewed is not None
    call(
        backend, "playlist_save", playlist_revision=draft(backend), token=reviewed.token
    )
    assert len(backend.engine.active.library.tracks) == prior_count + 1
    playlist = next(
        p
        for p in backend.engine.active.library.playlists
        if p.name == "Only selected songs"
    )
    assert (
        len(playlist.entries) == 1 and str(playlist.entries[0].track_id) != existing_id
    )
