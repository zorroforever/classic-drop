"""Bounded native Playlist DTOs and generation-owned semantic adapter."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from threading import Event
from typing import TYPE_CHECKING
from uuid import uuid4

from classic_drop.library_changes import (
    ExistingTrackSelection,
    ImportDestination,
    ImportQueueCarryover,
    ImportQueueState,
    PlaylistLibraryReview,
)
from classic_drop.playlist_protocol import (
    PlaylistDraftDTO,
    _boolean,
    _keys,
    _object,
    _sequence,
    _text,
    domain_id,
    playlist_draft_dto,
    playlist_entries_dto,
    playlist_summaries,
    smart_field_descriptors,
)
from classic_drop.playlists import PlaylistEdit, PlaylistSession

if TYPE_CHECKING:
    from classic_drop.native_backend import NativeBackend
    from classic_drop.native_protocol import Request, Result, TrackDTO
    from iPodDB.library import LibraryChange
    from iPodDB.library.playlists import SmartPlaylist


@dataclass(frozen=True, slots=True)
class ImportDestinationDTO:
    playlist_ids: tuple[str, ...] = ()
    new_name: str | None = None
    parent_id: str | None = None
    keep_empty_new: bool = False

    def domain(self) -> ImportDestination:
        return ImportDestination(
            tuple(domain_id(i) for i in self.playlist_ids),
            self.new_name,
            None if self.parent_id is None else domain_id(self.parent_id),
            self.keep_empty_new,
        )


def destination_from_json(raw: object) -> ImportDestinationDTO:
    value = _object(raw)
    _keys(value, set(), set(ImportDestinationDTO.__dataclass_fields__))
    result = ImportDestinationDTO(
        tuple(str(domain_id(i)) for i in _sequence(value.get("playlist_ids", []))),
        None if value.get("new_name") is None else _text(value["new_name"]),
        None if value.get("parent_id") is None else str(domain_id(value["parent_id"])),
        _boolean(value.get("keep_empty_new", False)),
    )
    result.domain()
    return result


@dataclass(frozen=True, slots=True)
class ExistingTrackDTO:
    token: str
    track_id: str


def reuse_from_json(raw: object) -> tuple[ExistingTrackDTO, ...]:
    result = []
    for item in _sequence(raw):
        value = _object(item)
        _keys(value, {"token", "track_id"})
        result.append(
            ExistingTrackDTO(_text(value["token"]), str(domain_id(value["track_id"])))
        )
    if len({i.token for i in result}) != len(result):
        raise ValueError("An existing Track choice is repeated")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class PlaylistChangeDTO:
    subject: str
    identity: str
    action: str
    name: str
    fields: tuple[str, ...]
    origin: str


@dataclass(frozen=True, slots=True)
class PlaylistReviewDTO:
    token: str
    operation: str
    added: int
    reused: int
    no_changes: bool
    change_count: int
    changes: tuple[PlaylistChangeDTO, ...]


@dataclass(frozen=True, slots=True)
class PlaylistIdentityDTO:
    draft_id: str
    output_id: str


@dataclass(frozen=True, slots=True)
class _Upload:
    revision: str
    edit: PlaylistEdit
    expected_count: int
    chunks: tuple[tuple[str, tuple[str, ...]], ...] = ()
    byte_count: int = 0


def bounded_page[T](rows: tuple[T, ...], offset: int, limit: int) -> tuple[T, ...]:
    """Fit complete rows, leaving envelope space; never truncate a rule or record."""
    fitted: list[T] = []
    size = 0
    for row in rows[offset : offset + limit]:
        encoded = json.dumps(asdict(row), ensure_ascii=False).encode("utf-8")  # type: ignore[call-overload]
        if size + len(encoded) > 800_000:
            if not fitted:
                raise ValueError(
                    "A complete Playlist record exceeds the native transport limit"
                )
            break
        fitted.append(row)
        size += len(encoded)
    return tuple(fitted)


class NativePlaylists:
    """Host draft, upload, queue intent and issued Review for one native generation."""

    def __init__(self, backend: NativeBackend) -> None:
        self.backend = backend
        self.session: PlaylistSession | None = None
        self.review: PlaylistLibraryReview | None = None
        self.review_token = ""
        self.uploads: dict[str, _Upload] = {}
        self.destination = ImportDestinationDTO()
        self.reuse: tuple[ExistingTrackDTO, ...] = ()
        self.allow_duplicates: tuple[str, ...] = ()
        self.carryover: ImportQueueCarryover | None = None
        self.requires_reselection = False
        self.preview_key: tuple[str, SmartPlaylist, int | None] | None = None
        self.preview_rows: tuple[TrackDTO, ...] = ()
        self.queue_source = backend.engine.coordinator.active_ipod
        backend.engine.library_changes.bind_queue(self.queue_state)

    def queue_state(self) -> ImportQueueState:
        b = self.backend
        return ImportQueueState(
            b.revision,
            tuple(b.entries.values()),
            self.destination.domain(),
            tuple(
                ExistingTrackSelection(i.token, domain_id(i.track_id))
                for i in self.reuse
            ),
            self.allow_duplicates,
            self.queue_source,
        )

    def reset(self) -> None:
        self.session = None
        self.preview_key = None
        self.preview_rows = ()
        self.uploads.clear()
        self.destination = ImportDestinationDTO()
        self.reuse = ()
        self.allow_duplicates = ()
        self.carryover = None
        self.requires_reselection = False
        self.queue_source = self.backend.engine.coordinator.active_ipod
        self.invalidate()

    def invalidate(self) -> None:
        self.review = None
        self.review_token = ""
        self.backend.engine.library_changes.invalidate()

    def current(self) -> PlaylistSession:
        if self.session is None:
            self.session = PlaylistSession(self.backend.engine.active.library)
        return self.session

    def draft(self) -> PlaylistDraftDTO | None:
        return (
            None
            if self.backend.engine.coordinator.active_ipod is None
            else playlist_draft_dto(self.current())
        )

    def guard(self) -> None:
        if self.session is not None and self.session.dirty:
            raise ValueError(
                "Resolve unsaved Playlist changes by saving or discarding them first"
            )

    def discard_queue(self) -> None:
        self.carryover = None
        self.requires_reselection = False
        self.destination = ImportDestinationDTO()
        self.reuse = ()
        self.allow_duplicates = ()
        self.invalidate()

    def queue_changed(self) -> None:
        self.invalidate()
        tokens = set(self.backend.entries)
        self.reuse = tuple(i for i in self.reuse if i.token in tokens)
        self.allow_duplicates = tuple(i for i in self.allow_duplicates if i in tokens)

    def _review_dto(self, request: Request) -> PlaylistReviewDTO:
        review = self.review
        if review is None or (request.token and request.token != self.review_token):
            raise ValueError("The Playlist Review expired; check the changes again")
        rows: list[PlaylistChangeDTO] = []
        for origin, changes in (
            ("draft", review.changes),
            ("sidecar", review.sidecar_changes),
            ("smart", review.smart_refresh_changes),
        ):
            rows.extend(self._change(change, origin) for change in changes)
        return PlaylistReviewDTO(
            self.review_token,
            review.operation,
            review.added,
            review.reused,
            review.no_changes,
            len(rows),
            bounded_page(tuple(rows), request.offset, request.limit),
        )

    @staticmethod
    def _change(change: LibraryChange, origin: str) -> PlaylistChangeDTO:
        return PlaylistChangeDTO(
            change.subject,
            str(change.record_id) if change.record_id is not None else "",
            change.action,
            change.name,
            change.fields,
            origin,
        )

    def execute(self, request: Request, cancelled: Event) -> Result:
        b = self.backend
        session = self.current()
        command = request.command
        if request.playlist_revision or command not in {
            "playlist_list",
            "playlist_entries",
            "playlist_fields",
        }:
            session.require_revision(request.playlist_revision)
        if command == "playlist_list":
            rows = playlist_summaries(session)
            return replace(
                b._result(total=len(rows), offset=request.offset),
                playlist_items=bounded_page(rows, request.offset, request.limit),
            )
        if command == "playlist_entries":
            entry_rows = playlist_entries_dto(
                session.snapshot, domain_id(request.token)
            )
            return replace(
                b._result(total=len(entry_rows), offset=request.offset),
                playlist_entries=bounded_page(
                    entry_rows, request.offset, request.limit
                ),
            )
        if command == "playlist_fields":
            field_rows = smart_field_descriptors()
            # Playlist choices are independently paged to avoid an unbounded descriptor.
            return replace(
                b._result(total=len(field_rows), offset=request.offset),
                smart_fields=bounded_page(field_rows, request.offset, request.limit),
            )
        if command == "playlist_preview":
            if request.smart is None:
                raise ValueError("Provide a complete Smart Playlist configuration")
            from classic_drop.native_backend import track_dto

            playlist_id = domain_id(request.token) if request.token else None
            key = (session.revision, request.smart, playlist_id)
            if request.offset == 0:
                tracks = session.preview(
                    request.smart,
                    playlist_id=playlist_id,
                    checkpoint=lambda: b.engine._checkpoint(cancelled),
                )
                b.engine._checkpoint(cancelled)
                self.preview_key = key
                self.preview_rows = tuple(track_dto(t) for t in tracks)
            elif self.preview_key != key:
                raise ValueError("The Smart Playlist preview expired; preview again")
            return replace(
                b._result(total=len(self.preview_rows), offset=request.offset),
                tracks=bounded_page(self.preview_rows, request.offset, request.limit),
            )
        if command in {
            "playlist_edit_begin",
            "playlist_edit_chunk",
            "playlist_edit_finish",
            "playlist_edit_cancel",
        }:
            return self._upload(request, cancelled)
        if command == "playlist_edit":
            if request.playlist_edit is None:
                raise ValueError("Provide a Playlist action")
            outcome = session.edit(
                request.playlist_edit, expected_revision=request.playlist_revision
            )
            self.uploads.clear()
            self.invalidate()
            b._invalidate_review()
            return b._result(count=outcome.skipped_duplicates)
        if command in {"playlist_undo", "playlist_redo", "playlist_discard"}:
            getattr(session, command.removeprefix("playlist_"))(
                expected_revision=request.playlist_revision
            )
            self.uploads.clear()
            self.invalidate()
            b._invalidate_review()
            return b._result()
        if command == "import_destination":
            if request.revision != b.revision:
                raise ValueError("The import queue changed; reload")
            destination = request.destination or ImportDestinationDTO()
            ids = {p.playlist_id: p for p in session.snapshot.playlists}
            for identity in destination.domain().playlist_ids:
                p = ids.get(identity)
                if p is None or p.kind.value != "playlist" or p.system_managed:
                    raise ValueError("Choose current ordinary Playlists")
            if destination.parent_id is not None:
                parent = ids.get(domain_id(destination.parent_id))
                if (
                    parent is None
                    or parent.kind.value != "folder"
                    or parent.system_managed
                ):
                    raise ValueError("Choose a current Playlist Folder")
            if (
                not {i.token for i in request.reuse} <= b.entries.keys()
                or not set(request.allow_duplicates) <= b.entries.keys()
            ):
                raise ValueError("The import queue tokens expired")
            self.destination, self.reuse, self.allow_duplicates = (
                destination,
                request.reuse,
                request.allow_duplicates,
            )
            b.revision = uuid4().hex
            self.requires_reselection = False
            self.invalidate()
            return b._result()
        if command == "queue_reprepare":
            if self.carryover is None or request.revision != b.revision:
                raise ValueError("There is no current Host queue intent to prepare")
            entries = b.engine.library_changes.reprepare_intents(
                self.carryover, cancelled
            )
            b.entries = {e.token: e for e in entries}
            b.revision = uuid4().hex
            self.carryover = None
            self.queue_source = b.engine.active
            self.queue_changed()
            return b._preview_page(request)
        if command == "playlist_prepare":
            self.invalidate()
            if request.include_imports and self.requires_reselection:
                raise ValueError(
                    "Choose the import destination again before checking imports"
                )
            if request.include_imports and self.carryover is not None:
                raise ValueError(
                    "Prepare the retained Host queue again before checking imports"
                )
            if request.include_imports and request.revision != b.revision:
                raise ValueError("The import queue changed; reload")
            self.review = b.engine.library_changes.prepare(
                session,
                tuple(b.entries.values()) if request.include_imports else (),
                self.destination.domain()
                if request.include_imports
                else ImportDestination(),
                cancelled,
                reuse=tuple(
                    ExistingTrackSelection(i.token, domain_id(i.track_id))
                    for i in self.reuse
                )
                if request.include_imports
                else (),
                allow_duplicates=self.allow_duplicates
                if request.include_imports
                else (),
            )
            self.review_token = uuid4().hex
            return replace(
                b._result(),
                playlist_review=self._review_dto(replace(request, token="")),
            )
        if command == "playlist_review":
            return replace(
                b._result(offset=request.offset),
                playlist_review=self._review_dto(request),
            )
        if command == "playlist_save":
            if (
                self.review is None
                or not request.token
                or request.token != self.review_token
            ):
                raise ValueError("The Playlist Review expired; check the changes again")
            review, self.review = self.review, None
            saved = b.engine.library_changes.save(review, cancelled)
            carryover = saved.queue_carryover
            b._sync()
            if carryover is not None:
                self.carryover = carryover
                self.requires_reselection = carryover.requires_reselection
                d = carryover.destination
                self.destination = (
                    ImportDestinationDTO()
                    if d is None
                    else ImportDestinationDTO(
                        tuple(str(i) for i in d.playlist_ids),
                        d.new_name,
                        None if d.parent_id is None else str(d.parent_id),
                        d.keep_empty_new,
                    )
                )
            return replace(
                b._result(count=saved.added, warnings=saved.warnings),
                playlist_id_map=tuple(
                    PlaylistIdentityDTO(str(a), str(z)) for a, z in saved.playlist_ids
                ),
            )
        raise ValueError(f"Unknown Playlist command: {command}")

    def _upload(self, request: Request, cancelled: Event) -> Result:
        b, session = self.backend, self.current()
        if request.command == "playlist_edit_begin":
            if (
                request.playlist_edit is None
                or request.playlist_edit.track_ids
                or request.playlist_edit.entry_ids
            ):
                raise ValueError("Begin an action without selection arrays")
            if not 1 <= request.batch_count <= 1_000_000:
                raise ValueError("Declare the complete Playlist action selection count")
            if len(self.uploads) >= 4:
                raise ValueError("Cancel an incomplete Playlist action first")
            token = uuid4().hex
            self.uploads[token] = _Upload(
                session.revision, request.playlist_edit, request.batch_count
            )
            return replace(b._result(), batch_token=token)
        upload = self.uploads.get(request.token)
        if upload is None or upload.revision != request.playlist_revision:
            raise ValueError("The Playlist action upload expired")
        if request.command == "playlist_edit_cancel":
            del self.uploads[request.token]
            return b._result()
        if request.command == "playlist_edit_chunk":
            if (
                request.offset != len(upload.chunks)
                or request.source not in {"tracks", "entries"}
                or not request.ids
            ):
                raise ValueError("Invalid Playlist action chunk sequence")
            if request.source == "tracks":
                for identity in request.ids:
                    domain_id(identity)
            else:
                for identity in request.ids:
                    _text(identity)
            size = upload.byte_count + sum(
                len(i.encode("utf-8")) + 8 for i in request.ids
            )
            count = sum(len(ids) for _source, ids in upload.chunks) + len(request.ids)
            if count > upload.expected_count:
                raise ValueError("Playlist action chunk exceeds its declared selection")
            if size > 16 * 1024 * 1024 or len(upload.chunks) >= 1024:
                raise ValueError(
                    "Playlist action upload exceeds the bounded staging limit"
                )
            self.uploads[request.token] = replace(
                upload,
                chunks=(*upload.chunks, (request.source, request.ids)),
                byte_count=size,
            )
            return b._result()
        if sum(len(ids) for _source, ids in upload.chunks) != upload.expected_count:
            raise ValueError("The Playlist action upload is incomplete")
        del self.uploads[request.token]
        edit = replace(
            upload.edit,
            track_ids=tuple(
                domain_id(i)
                for source, ids in upload.chunks
                if source == "tracks"
                for i in ids
            ),
            entry_ids=tuple(
                i for source, ids in upload.chunks if source == "entries" for i in ids
            ),
        )
        b.engine._checkpoint(cancelled)
        return self.execute(
            replace(request, command="playlist_edit", playlist_edit=edit), cancelled
        )
