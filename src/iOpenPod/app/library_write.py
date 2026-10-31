"""Immutable write-workflow messages, independent of controllers and Qt."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from typing import TYPE_CHECKING, Literal, Protocol

from iPodDB.library import LibrarySnapshot, Playlist, Track, TrackMetadata

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from iOpenPod.app.media.importing import LibraryMediaSource
    from iOpenPod.app.media.progress import MediaPreparationProgress
    from iOpenPod.app.models.device import ActiveIPod
    from iPodDB.library import (
        ArtworkAsset,
        ArtworkPixels,
        ArtworkRead,
        FileDependency,
        LibraryWritePlan,
        LibraryWriteResult,
        PreparedPhoto,
        TimedArtworkAsset,
        WriteIssue,
        WriteResources,
    )


class PreparationCancelledError(Exception):
    """The caller stopped work at a checkpoint before publication."""


@dataclass(frozen=True, slots=True)
class RockboxMediaUpdate:
    """Retag one retained iPod media file without replacing its audio payload."""

    track_id: int
    artwork: ArtworkPixels | None
    preserve_artwork: bool = False
    artwork_read: ArtworkRead | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class LibraryPreparationRequest:
    """Capture desired state and its application source together exactly once.

    The coordinator binds this snapshot to the retained iPodDB source only after
    checking ``source``. Workspace revisions identify the edit being reviewed;
    they are not the iPodDB source revision or permission to save device files.
    """

    snapshot: LibrarySnapshot
    source: ActiveIPod
    workspace_generation: int
    workspace_revision: int
    delete_omissions: bool = field(default=False, kw_only=True)
    reconcile_sidecars: bool = field(default=False, kw_only=True)
    artwork: tuple[ArtworkAsset | TimedArtworkAsset, ...] = field(
        default=(), kw_only=True
    )
    media: tuple[LibraryMediaSource, ...] = field(default=(), kw_only=True)
    replace_media: tuple[int, ...] = field(default=(), kw_only=True)
    rockbox_media: tuple[RockboxMediaUpdate, ...] = field(default=(), kw_only=True)
    rockbox_metadata: bool = field(default=False, kw_only=True)
    photos: tuple[PreparedPhoto, ...] = field(default=(), kw_only=True)
    replace_photos: tuple[int, ...] = field(default=(), kw_only=True)
    discard_removed_track_media: bool = field(default=False, kw_only=True)
    device_recovery: bool = field(default=False, kw_only=True)
    regenerate_sqlite: bool = field(default=False, kw_only=True)
    rebuild_album_indexes: bool = field(default=False, kw_only=True)
    repair_podcast_links: bool = field(default=False, kw_only=True)
    normalize_podcasts: bool = field(default=False, kw_only=True)
    # Retained media whose embedded covers supplied new native artwork.
    artwork_dependencies: tuple[FileDependency, ...] = field(default=(), kw_only=True)


def overlay_sidecar_snapshot(
    original: LibrarySnapshot,
    desired: LibrarySnapshot,
    projected: LibrarySnapshot,
) -> LibrarySnapshot:
    """Apply source-bound semantic edits to a fresh, isolated sidecar projection.

    Unedited fields and newly observed records belong to the projection. Existing
    records are matched only by stable identity; overlapping changes and new-ID
    collisions require reloading and manually reapplying the Host intent.
    """
    return replace(
        projected,
        tracks=_overlay_records(
            original.tracks, desired.tracks, projected.tracks, lambda t: t.track_id
        ),
        playlists=_overlay_records(
            original.playlists,
            desired.playlists,
            projected.playlists,
            lambda p: p.playlist_id,
        ),
        device_name=desired.device_name
        if desired.device_name != original.device_name
        else projected.device_name,
        photos=desired.photos
        if desired.photos != original.photos
        else projected.photos,
    )


def _overlay_records[Record: (Track, Playlist)](
    original: tuple[Record, ...],
    desired: tuple[Record, ...],
    projected: tuple[Record, ...],
    identity: Callable[[Record], int],
) -> tuple[Record, ...]:
    baseline = {identity(record): record for record in original}
    fresh = {identity(record): record for record in projected}
    if not baseline.keys() <= fresh.keys():
        raise ValueError(
            "Sidecar projection lost a source identity. Reload the Library."
        )
    result: list[Record] = []
    for record in desired:
        key = identity(record)
        if key in baseline:
            result.append(_overlay_fields(baseline[key], record, fresh[key]))
        elif key in fresh:
            raise ValueError(
                f"Host and sidecar additions share identity {key}. Reload and reapply the edit."
            )
        else:
            result.append(record)
    result.extend(record for record in projected if identity(record) not in baseline)
    return tuple(result)


def _overlay_fields[Record: (Track, TrackMetadata, Playlist)](
    original: Record, desired: Record, projected: Record
) -> Record:
    result = projected
    for definition in fields(original):
        name = definition.name
        before, requested, observed = (
            getattr(record, name) for record in (original, desired, projected)
        )
        if requested == before:
            continue
        if (
            isinstance(before, TrackMetadata)
            and isinstance(requested, TrackMetadata)
            and isinstance(observed, TrackMetadata)
        ):
            requested = _overlay_fields(before, requested, observed)
        elif observed != before and observed != requested:
            raise ValueError(
                f"Host and sidecar edits conflict on {name}. Reload and reapply the edit."
            )
        result = replace(result, **{name: requested})
    return result


@dataclass(frozen=True, slots=True)
class WriteItemProgress:
    """One active item's display identity and activity; confers no file authority."""

    item_id: str
    name: str
    progress: MediaPreparationProgress


@dataclass(frozen=True, slots=True)
class WriteProgress:
    """An entered stage, not proof that the stage completed successfully.

    ``completed`` and ``total`` describe the current stage only. They are
    optional because validation and database phases do not always have a useful
    item count. ``current_item`` is a human-readable identity for the item
    most recently started or completed by the stage; it is deliberately not a
    permission-bearing path.

    ``active_items`` is the complete immutable snapshot of currently running Host
    preparations. It excludes waiting and finished items; measurements describe
    each item's current phase rather than readiness for publication.
    """

    phase: str
    message: str
    completed: int | None = None
    total: int | None = None
    current_item: str = ""
    unit: str = ""
    active_items: tuple[WriteItemProgress, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class WriteTraceEvent:
    phase: str
    message: str
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class LibraryFileChange:
    """Reviewable file effects; these descriptions confer no save authority."""

    path: str
    action: Literal["write", "remove", "delete"]
    size_bytes: int
    sha256: str | None


@dataclass(frozen=True, slots=True)
class LibraryReview:
    plan: LibraryWritePlan | None
    result: LibraryWriteResult
    resources: WriteResources | None = field(default=None, kw_only=True)
    file_changes: tuple[LibraryFileChange, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class LibrarySaveResult:
    issues: tuple[WriteIssue, ...]
    active: ActiveIPod | None = None
    recovery_path: str = ""


class LibraryPreparationService(Protocol):
    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibraryReview: ...

    def save_library(
        self,
        review: LibraryReview,
        expected: ActiveIPod,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibrarySaveResult: ...
