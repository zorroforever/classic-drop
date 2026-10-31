"""Reviewed, isolated Playlist and music-import changes for Classic Drop."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from threading import Event
from typing import TYPE_CHECKING, Literal

from classic_drop.playlists import PlaylistSession
from iOpenPod.app.library_write import LibraryPreparationRequest, LibraryReview
from iPodDB.library import LibraryChange, LibrarySnapshot, PlaylistKind
from storage import DevicePath

if TYPE_CHECKING:
    from classic_drop.engine import ClassicDropEngine, PreviewEntry
    from classic_drop.media import PreparedSong
    from iOpenPod.app.models.device import ActiveIPod


@dataclass(frozen=True, slots=True)
class ImportDestination:
    """Exactly one library, ordinary-Playlist selection, or new-Playlist intent."""

    playlist_ids: tuple[int, ...] = ()
    new_name: str | None = None
    parent_id: int | None = None
    keep_empty_new: bool = False

    def __post_init__(self) -> None:
        if self.playlist_ids and self.new_name is not None:
            raise ValueError("Choose existing Playlists or one new Playlist")
        if len(set(self.playlist_ids)) != len(self.playlist_ids):
            raise ValueError("A Playlist destination is repeated")
        if self.new_name is not None and not self.new_name.strip():
            raise ValueError("A new Playlist needs a name")
        if self.parent_id is not None and self.new_name is None:
            raise ValueError("Only a new Playlist can have a destination folder")


@dataclass(frozen=True, slots=True)
class ExistingTrackSelection:
    token: str
    track_id: int


@dataclass(frozen=True, slots=True)
class ImportQueueState:
    """Owner's complete immutable queue intent, with an opaque edit revision."""

    revision: str
    entries: tuple[PreviewEntry, ...] = ()
    destination: ImportDestination = ImportDestination()
    reuse: tuple[ExistingTrackSelection, ...] = ()
    allow_duplicates: tuple[str, ...] = ()
    source: ActiveIPod | None = None


@dataclass(frozen=True, slots=True)
class HostImportIntent:
    key: str
    entry: PreviewEntry


@dataclass(frozen=True, slots=True)
class ImportQueueCarryover:
    """Host intent only: every source-bound token and reuse authority has expired."""

    intents: tuple[HostImportIntent, ...]
    destination: ImportDestination | None
    requires_reselection: bool = False
    allow_high_resolution_alac: bool = False


@dataclass(frozen=True, slots=True)
class PlaylistLibraryReview:
    source: ActiveIPod
    session_revision: str
    queue_revision: str
    library_review: LibraryReview
    operation: Literal["playlist", "import"]
    added: int
    reused: int
    changes: tuple[LibraryChange, ...]
    sidecar_changes: tuple[LibraryChange, ...]
    smart_refresh_changes: tuple[LibraryChange, ...]
    destination_playlist_ids: tuple[int, ...]

    @property
    def no_changes(self) -> bool:
        return not self.library_review.file_changes


@dataclass(frozen=True, slots=True)
class PlaylistLibrarySaveResult:
    active: ActiveIPod
    added: int
    reused: int
    recovery_path: str
    playlist_ids: tuple[tuple[int, int], ...] = ()
    warnings: tuple[str, ...] = ()
    queue_carryover: ImportQueueCarryover | None = None


@dataclass(frozen=True, slots=True)
class _IssuedReview:
    review: PlaylistLibraryReview
    session: PlaylistSession
    queue: ImportQueueState
    import_revision: str
    prepared: tuple[tuple[PreviewEntry, PreparedSong], ...]
    added_ids: tuple[int, ...]
    reuse: tuple[ExistingTrackSelection, ...]
    allow_high_resolution_alac: bool


def _changes(
    before: LibrarySnapshot, after: LibrarySnapshot
) -> tuple[LibraryChange, ...]:
    result: list[LibraryChange] = []
    for subject, old_records, new_records, identity in (
        ("track", before.tracks, after.tracks, "track_id"),
        ("playlist", before.playlists, after.playlists, "playlist_id"),
    ):
        old = {getattr(item, identity): item for item in old_records}
        new = {getattr(item, identity): item for item in new_records}
        for key, item in old.items():
            if key not in new:
                result.append(
                    LibraryChange(
                        subject,
                        key,
                        "delete",
                        getattr(item, "name", getattr(item, "title", "")),
                    )
                )
        for key, item in new.items():
            name = getattr(item, "name", getattr(item, "title", ""))
            if key not in old:
                result.append(LibraryChange(subject, key, "add", name))
            elif item != old[key]:
                changed = tuple(
                    field.name
                    for field in fields(item)
                    if getattr(item, field.name) != getattr(old[key], field.name)
                )
                result.append(LibraryChange(subject, key, "update", name, changed))
    return tuple(result)


class PlaylistLibraryChanges:
    """Engine-owned authority for exact reviewed candidates on one Active iPod."""

    def __init__(self, engine: ClassicDropEngine) -> None:
        self._engine = engine
        self._issued: _IssuedReview | None = None
        self._queue: Callable[[], ImportQueueState] | None = None

    def bind_queue(self, current: Callable[[], ImportQueueState]) -> None:
        """Bind the UI owner's acknowledged edits, covers, destinations and choices."""
        self.invalidate()
        self._queue = current

    def invalidate(self) -> None:
        self._issued = None

    def prepare(
        self,
        session: PlaylistSession,
        entries: tuple[PreviewEntry, ...],
        destination: ImportDestination,
        cancelled: Event,
        *,
        reuse: tuple[ExistingTrackSelection, ...] = (),
        allow_duplicates: tuple[str, ...] = (),
    ) -> PlaylistLibraryReview:
        engine = self._engine
        self.invalidate()
        engine._checkpoint(cancelled)
        engine._require_writes_allowed()
        active = engine.active
        session_revision = session.revision
        import_revision = engine.import_revision
        session.require_revision(session_revision)
        if session.original_snapshot is not active.library:
            raise ValueError("The Playlist draft source changed; reload the Library")
        desired = session.snapshot
        # delete_omissions is needed for Playlist deletion, never Track deletion.
        if (desired.tracks, desired.photos, desired.device_name) != (
            active.library.tracks,
            active.library.photos,
            active.library.device_name,
        ):
            raise ValueError(
                "Playlist changes must preserve every existing Track and its resources"
            )
        queue = (
            self._queue()
            if self._queue is not None
            else ImportQueueState(
                engine.import_revision, engine.prepared_entries, source=active
            )
        )
        if (
            entries
            and self._queue is not None
            and (entries, destination, reuse, allow_duplicates)
            != (queue.entries, queue.destination, queue.reuse, queue.allow_duplicates)
        ):
            raise ValueError("The import queue changed; review its current choices")
        if entries and queue.source is not None and queue.source is not active:
            raise ValueError("The import queue source changed; prepare its files again")
        selected = tuple(entry for entry in entries if entry.selected)
        prepared = (
            engine.validate_import_entries(entries, cancelled) if selected else ()
        )
        by_token = {entry.token: item for entry, item in prepared}
        if (
            len({choice.token for choice in reuse}) != len(reuse)
            or not {choice.token for choice in reuse} <= by_token.keys()
        ):
            raise ValueError(
                "Existing Track choices must identify selected source tokens"
            )
        reused = {choice.token: choice.track_id for choice in reuse}
        if not set(allow_duplicates) <= by_token.keys():
            raise ValueError("Duplicate authorization must identify selected sources")
        original_entries = {entry.token: entry for entry in engine.prepared_entries}
        for entry, _item in prepared:
            if (
                entry.token not in reused
                and original_entries[entry.token].status != "new"
                and entry.token not in allow_duplicates
            ):
                raise ValueError(
                    "Resolve the duplicate by selecting an existing Track or authorizing a copy"
                )
        self._verify_reuse(active, prepared, reuse, cancelled)
        copies = tuple(pair for pair in prepared if pair[0].token not in reused)
        workspace, added_ids = engine.build_import_workspace(desired, copies)
        ids_by_token = (
            dict(zip((entry.token for entry, _item in copies), added_ids, strict=True))
            | reused
        )
        ordered_ids = tuple(ids_by_token[entry.token] for entry in selected)
        destinations = destination.playlist_ids
        for playlist_id in destinations:
            target = workspace.playlist(playlist_id)
            if (
                target is None
                or target.kind is not PlaylistKind.PLAYLIST
                or target.system_managed
            ):
                raise ValueError("Select an existing ordinary Playlist destination")
        if destination.new_name is not None:
            if not ordered_ids and not destination.keep_empty_new:
                raise ValueError(
                    "Choose whether to keep an empty new Playlist or cancel its creation"
                )
            target = workspace.create(
                PlaylistKind.PLAYLIST,
                destination.new_name,
                parent_id=destination.parent_id,
            )
            destinations = (target.playlist_id,)
        for playlist_id in destinations:
            target = workspace.playlist(playlist_id)
            assert target is not None
            retained = set(target.track_ids)
            workspace.set_tracks(
                playlist_id,
                (
                    *target.track_ids,
                    *(
                        track_id
                        for track_id in dict.fromkeys(ordered_ids)
                        if track_id not in retained
                    ),
                ),
            )
        candidate = workspace.desired_snapshot()
        library_review = engine.coordinator.prepare_library(
            LibraryPreparationRequest(
                candidate,
                active,
                workspace.generation,
                workspace.revision,
                delete_omissions=True,
                reconcile_sidecars=True,
                artwork=workspace.artwork_assets,
                media=workspace.media_sources,
            ),
            engine.progress,
            cancelled,
            allow_unchanged=True,
        )
        engine._checkpoint(cancelled)
        session.require_revision(session_revision)
        if engine.active is not active or engine.import_revision != import_revision:
            raise ValueError("The device or import queue changed during preparation")
        if self._queue is not None and self._queue() != queue:
            raise ValueError("The import queue changed during preparation")
        if library_review.result.prepared is None or library_review.plan is None:
            raise ValueError(
                "\n".join(
                    f"{issue.code}: {issue.message} {issue.detail}"
                    for issue in library_review.result.issues
                )
            )
        retained_paths = {
            track.metadata.location.casefold() for track in active.library.tracks
        }
        if any(
            change.path.casefold() in retained_paths
            for change in library_review.file_changes
        ):
            raise ValueError(
                "Playlist/import changes cannot delete or overwrite retained music"
            )
        if not copies and any(
            change.path.casefold().startswith("ipod_control/artwork/")
            for change in library_review.file_changes
        ):
            raise ValueError("Playlist-only changes cannot rewrite retained artwork")
        derived = _changes(candidate, library_review.plan.draft.snapshot)
        live_smart_ids = {
            playlist.playlist_id
            for playlist in candidate.playlists
            if playlist.kind is PlaylistKind.SMART
            and playlist.smart is not None
            and playlist.smart.live_update
        }
        smart_changes = tuple(
            change
            for change in derived
            if change.subject == "playlist"
            and change.record_id in live_smart_ids
            and change.fields == ("entries",)
        )
        review = PlaylistLibraryReview(
            active,
            session_revision,
            queue.revision,
            library_review,
            "import" if selected else "playlist",
            len(copies),
            len(reuse),
            _changes(active.library, candidate),
            tuple(change for change in derived if change not in smart_changes),
            smart_changes,
            destinations,
        )
        self._issued = _IssuedReview(
            review,
            session,
            queue,
            import_revision,
            prepared,
            added_ids,
            reuse,
            engine.import_original_alac,
        )
        return review

    def _verify_reuse(
        self,
        active: ActiveIPod,
        prepared: tuple[tuple[PreviewEntry, PreparedSong], ...],
        reuse: tuple[ExistingTrackSelection, ...],
        cancelled: Event,
    ) -> None:
        if not reuse:
            return
        songs = {entry.token: item for entry, item in prepared}
        tracks = {track.track_id: track for track in active.library.tracks}
        with self._engine.coordinator.sync_session(active) as session:
            for choice in reuse:
                self._engine._checkpoint(cancelled)
                track = tracks.get(choice.track_id)
                if track is None:
                    raise ValueError(
                        "The selected existing Track is no longer in the Library"
                    )
                observed = session.fingerprint(DevicePath(track.metadata.location))
                if (observed.sha256, observed.size) != (
                    songs[choice.token].original.sha256,
                    songs[choice.token].original.size,
                ):
                    raise ValueError(
                        "The selected existing Track does not match the source content"
                    )

    def save(
        self, review: PlaylistLibraryReview, cancelled: Event
    ) -> PlaylistLibrarySaveResult:
        engine, issued = self._engine, self._issued
        engine._checkpoint(cancelled)
        engine._require_writes_allowed()
        if (
            issued is None
            or issued.review is not review
            or review.source is not engine.active
        ):
            raise ValueError("This Review expired; check the Library changes again")
        # One save attempt consumes this authority, including failed source checks.
        # Restoring old evidence must never make a previously stale Review usable.
        self.invalidate()
        issued.session.require_revision(review.session_revision)
        issued.session.set_locked(True)
        try:
            self._require_queue(issued)
            if issued.prepared:
                engine.validate_import_entries(
                    tuple(entry for entry, _item in issued.prepared), cancelled
                )
                self._verify_reuse(
                    review.source, issued.prepared, issued.reuse, cancelled
                )
            self._require_queue(issued)
            result = engine.coordinator.save_library(
                review.library_review,
                review.source,
                engine.progress,
                cancelled,
                retain_recovery=True,
            )
            if result.active is None:
                engine.pending_recovery = result.recovery_path or None
                raise ValueError(
                    "\n".join(
                        f"{issue.code}: {issue.message} {issue.detail}"
                        for issue in result.issues
                    )
                    + f"\nRecovery record: {result.recovery_path}"
                )
            prepared = review.library_review.result.prepared
            assert prepared is not None
            mappings = {
                (mapping.subject, mapping.draft_id): mapping.output_id
                for mapping in prepared.identities
            }
            playlist_ids = tuple(
                (mapping.draft_id, mapping.output_id)
                for mapping in prepared.identities
                if mapping.subject == "playlist"
            )
            carryover = (
                self._carryover(
                    issued.queue,
                    result.active,
                    dict(playlist_ids),
                    review.source,
                    issued.allow_high_resolution_alac,
                )
                if review.operation == "playlist"
                and issued.queue.entries
                and not review.no_changes
                else None
            )
            if result.recovery_path:
                try:
                    if review.operation == "import":
                        copied = tuple(
                            (entry, item)
                            for entry, item in issued.prepared
                            if entry.token
                            not in {choice.token for choice in issued.reuse}
                        )
                        track_by_id = {
                            track.track_id: track
                            for track in result.active.library.tracks
                        }
                        receipts = []
                        for (_entry, item), draft_id in zip(
                            copied, issued.added_ids, strict=True
                        ):
                            track = track_by_id[mappings[("track", draft_id)]]
                            receipts.append(
                                (
                                    item.original.sha256,
                                    track.metadata.location,
                                    track.size_bytes,
                                )
                            )
                        engine.history.record(
                            engine._identity(), result.recovery_path, tuple(receipts)
                        )
                    else:
                        engine.history.record_operation(
                            engine._identity(), result.recovery_path, "playlist"
                        )
                except (OSError, ValueError, KeyError, sqlite3.Error) as error:
                    engine.pending_recovery = result.recovery_path
                    raise ValueError(
                        f"Library changes were saved, but their recovery index failed: {error}. Recovery record: {result.recovery_path}"
                    ) from error
            if not review.no_changes:
                engine.discard()
            return PlaylistLibrarySaveResult(
                result.active,
                review.added,
                review.reused,
                result.recovery_path,
                playlist_ids,
                tuple(f"{issue.message} {issue.detail}" for issue in result.issues),
                carryover,
            )
        finally:
            issued.session.set_locked(False)

    def _require_queue(self, issued: _IssuedReview) -> None:
        if self._engine.import_revision != issued.import_revision or (
            self._queue is not None and self._queue() != issued.queue
        ):
            raise ValueError(
                "The import queue changed; check the Library changes again"
            )

    @staticmethod
    def _carryover(
        queue: ImportQueueState,
        active: ActiveIPod,
        mappings: dict[int, int],
        source: ActiveIPod,
        allow_high_resolution_alac: bool,
    ) -> ImportQueueCarryover:
        available = {
            playlist.playlist_id: playlist for playlist in active.library.playlists
        }
        destination = queue.destination
        requested = (
            *destination.playlist_ids,
            *((destination.parent_id,) if destination.parent_id is not None else ()),
        )
        resolved = {
            identity: mappings.get(identity, identity) for identity in requested
        }
        valid = queue.source is source and all(
            output > 0 and output in available for output in resolved.values()
        )
        valid = valid and all(
            available[resolved[identity]].kind is PlaylistKind.PLAYLIST
            and not available[resolved[identity]].system_managed
            for identity in destination.playlist_ids
        )
        if destination.parent_id is not None:
            valid = (
                valid
                and available.get(resolved[destination.parent_id]) is not None
                and available[resolved[destination.parent_id]].kind
                is PlaylistKind.FOLDER
            )
        return ImportQueueCarryover(
            tuple(
                HostImportIntent(entry.token, replace(entry, token=""))
                for entry in queue.entries
            ),
            replace(
                destination,
                playlist_ids=tuple(
                    resolved[identity] for identity in destination.playlist_ids
                ),
                parent_id=resolved[destination.parent_id]
                if destination.parent_id is not None
                else None,
            )
            if valid
            else None,
            not valid,
            allow_high_resolution_alac,
        )

    def reprepare_intents(
        self, carryover: ImportQueueCarryover, cancelled: Event
    ) -> tuple[PreviewEntry, ...]:
        """Explicitly prepare fresh sources, restoring only Host metadata/selection intent."""
        entries = self._engine.preview(
            tuple(intent.entry.path for intent in carryover.intents),
            cancelled,
            allow_high_resolution_alac=carryover.allow_high_resolution_alac,
        )
        fresh = {entry.path: entry for entry in entries}
        return tuple(
            replace(
                fresh[intent.entry.path],
                title=intent.entry.title,
                artist=intent.entry.artist,
                album=intent.entry.album,
                album_artist=intent.entry.album_artist,
                track_number=intent.entry.track_number,
                disc_number=intent.entry.disc_number,
                artwork=intent.entry.artwork,
                selected=intent.entry.selected,
            )
            for intent in carryover.intents
        )
