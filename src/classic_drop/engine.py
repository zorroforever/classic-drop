"""Append workflow; every physical device mutation belongs to upstream Storage."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from uuid import uuid4

from classic_drop.history import ImportHistory
from classic_drop.media import PreparedSong, collect_audio, prepare_song
from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write import LibraryPreparationRequest, WriteProgress
from iOpenPod.app.media.importing import relocate_song
from iOpenPod.app.media.music_paths import MusicPathAllocator
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinator,
    SyncRecoveryRequiredError,
)
from iPodDB.library import ArtworkPixels
from storage import HostPath, Storage, capture_host_file


class OperationCancelledError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PreviewEntry:
    token: str
    path: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    track_number: int = 0
    disc_number: int = 0
    selected: bool = True
    status: str = "new"
    mode: str = "copy"
    length_ms: int = 0
    size_bytes: int = 0
    artwork: ArtworkPixels | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ImportResult:
    added: int
    recovery_path: str
    warnings: tuple[str, ...] = ()


class ClassicDropEngine:
    def __init__(
        self,
        *,
        data_directory: Path | None = None,
        coordinator: DeviceCoordinator | None = None,
        progress: Callable[[WriteProgress], None] = lambda _: None,
    ) -> None:
        self.directory = (
            data_directory or Path.home() / "Library/Application Support/Classic Drop"
        )
        self.history = ImportHistory(self.directory)
        self.coordinator = coordinator or DeviceCoordinator(
            Storage(
                writer_lock_directory=self.directory / "locks",
                transaction_recovery_directory=self.directory / "Recovery",
            ),
            volume_presentation_enabled=False,
        )
        self.coordinator.set_volume_presentation_enabled(False)
        self.progress = progress
        self._resources = ExitStack()
        self._songs: dict[str, PreparedSong] = {}
        self._preview_active: ActiveIPod | None = None
        self.pending_recovery: str | None = None
        self._entries: dict[Path, PreviewEntry] = {}

    @property
    def active(self) -> ActiveIPod:
        active = self.coordinator.active_ipod
        if active is None:
            raise ValueError(source_text("Select an iPod Classic first"))
        return active

    def discover(self) -> tuple[DeviceCandidate, ...]:
        return tuple(
            c
            for c in self.coordinator.discover_devices().candidates
            if c.profile is not None and c.profile.family == "iPod Classic"
        )

    def select(self, candidate_id: DeviceCandidateId) -> ActiveIPod:
        candidate = self.coordinator.discovery.candidate(candidate_id)
        if (
            candidate is None
            or candidate.profile is None
            or candidate.profile.family != "iPod Classic"
        ):
            raise ValueError(
                source_text("Only stock-firmware iPod Classic is supported")
            )
        if candidate.readiness not in (
            DeviceReadiness.READY,
            DeviceReadiness.SYNC_RECOVERY_REQUIRED,
        ):
            raise ValueError(
                source_text(
                    "Device library is not available: {state}",
                    state=candidate.readiness.value,
                )
            )
        self.discard()
        self.pending_recovery = None
        try:
            active = self.coordinator.select_device(
                candidate_id,
                reconcile_metadata=False,
                reconcile_sidecars=False,
                initialize_missing=False,
            )
        except SyncRecoveryRequiredError as error:
            self.pending_recovery = error.recovery_path
            raise
        if any(
            i.code.value == "artwork_database_unreadable"
            for i in active.candidate.issues
        ):
            self.coordinator.close()
            raise ValueError(
                source_text(
                    "Device artwork database is unreadable; restore a library backup first"
                )
            )
        return active

    def _identity(self) -> str:
        volume = self.coordinator.active_volume_id
        if volume is None:
            raise ValueError(source_text("The device is disconnected"))
        return volume.value

    def _checkpoint(self, cancelled: Event) -> None:
        if cancelled.is_set():
            raise OperationCancelledError(source_text("Operation canceled"))

    def preview(
        self, paths: tuple[Path, ...], cancelled: Event
    ) -> tuple[PreviewEntry, ...]:
        active = self.active
        if self._preview_active is not active:
            self.discard()
        self._preview_active = active

        def checkpoint() -> None:
            self._checkpoint(cancelled)

        receipts = self.history.receipts(self._identity())
        retained = {(t.metadata.location, t.size_bytes) for t in active.library.tracks}
        seen: set[str] = set()
        entries: list[PreviewEntry] = []
        with self.coordinator.sync_session(active) as session:
            device_root = session.mounted_volume.mount_point.path.resolve()
        sources = collect_audio(paths)
        for index, path in enumerate(sources):
            checkpoint()
            if path in self._entries:
                entry = self._entries[path]
                entries.append(entry)
                if entry.token in self._songs:
                    seen.add(self._songs[entry.token].original.sha256)
                continue
            self.progress(
                WriteProgress(
                    "inspect", "Inspecting music", index, len(sources), path.name
                )
            )
            token = uuid4().hex
            try:
                if path.resolve().is_relative_to(device_root):
                    raise ValueError(
                        source_text(
                            "Choose music from this Mac, not from the iPod itself"
                        )
                    )
                prepared = prepare_song(
                    path, active.profile, self._resources, checkpoint
                )
                song = prepared.song
                sha = prepared.original.sha256
                status = "new"
                if sha in seen:
                    status = "duplicate"
                elif receipts.get(sha) in retained:
                    status = "imported"
                elif any(
                    t.title.casefold() == song.track.title.casefold()
                    and t.artist.casefold() == song.track.artist.casefold()
                    and t.album.casefold() == song.track.album.casefold()
                    and abs(t.length_ms - song.track.length_ms) < 1500
                    for t in active.library.tracks
                ):
                    status = "possible_duplicate"
                seen.add(sha)
                self._songs[token] = prepared
                entries.append(
                    PreviewEntry(
                        token,
                        path,
                        song.track.title,
                        song.track.artist,
                        song.track.album,
                        song.track.album_artist,
                        song.track.track_number,
                        song.track.metadata.disc_number,
                        status == "new",
                        status,
                        prepared.mode,
                        song.track.length_ms,
                        song.track.size_bytes,
                        song.artwork,
                        "\n".join(prepared.warnings),
                    )
                )
            except OperationCancelledError:
                raise
            except Exception as error:
                entries.append(
                    PreviewEntry(
                        token,
                        path,
                        selected=False,
                        status="error",
                        detail=exception_text(error),
                    )
                )
        checkpoint()
        self._entries = {entry.path: entry for entry in entries}
        return tuple(entries)

    def commit(
        self, entries: tuple[PreviewEntry, ...], cancelled: Event
    ) -> ImportResult:
        def checkpoint() -> None:
            self._checkpoint(cancelled)

        checkpoint()
        active = self.active
        if active is not self._preview_active:
            raise ValueError(
                source_text("The device or library changed; preview again")
            )
        selected = tuple(e for e in entries if e.selected)
        if not selected:
            raise ValueError(source_text("Select at least one song to import"))
        prepared = []
        for entry in selected:
            checkpoint()
            item = self._songs.get(entry.token)
            if item is None or entry.path != item.path:
                raise ValueError(
                    source_text("The preview expired; select the files again")
                )
            if (
                not entry.title.strip()
                or min(entry.track_number, entry.disc_number) < 0
            ):
                raise ValueError(
                    source_text(
                        "A title is required and track and disc numbers cannot be negative"
                    )
                )
            with capture_host_file(
                HostPath(item.path), checkpoint=checkpoint
            ) as source:
                if source.fingerprint.sha256 != item.original.sha256:
                    raise ValueError(
                        source_text(
                            "File changed; preview it again: {name}",
                            name=item.path.name,
                        )
                    )
            prepared.append((entry, item))
        # Validate the retained database before the explicit commit's history
        # reconciliation. Initial selection and preview never reconcile it.
        with self.coordinator.sync_session(active):
            checkpoint()
        self.progress(WriteProgress("history", "Keeping playback history"))
        active = self.coordinator.select_device(
            active.candidate.id,
            reconcile_metadata=False,
            reconcile_sidecars=True,
            initialize_missing=False,
        )
        identity = self._identity()
        workspace = LibraryWorkspace()
        workspace.load(active.library)
        allocator = MusicPathAllocator(
            active.profile.capabilities.database.music_directory_count,
            (t.metadata.location for t in active.library.tracks),
        )
        for entry, item in prepared:
            song = item.song
            track = replace(
                song.track,
                title=entry.title.strip(),
                artist=entry.artist.strip(),
                album=entry.album.strip(),
                album_artist=entry.album_artist.strip(),
                track_number=entry.track_number,
                metadata=replace(song.track.metadata, disc_number=entry.disc_number),
            )
            song = replace(song, track=track, artwork=entry.artwork)
            song = relocate_song(
                song, allocator.allocate(Path(song.track.metadata.location).suffix[1:])
            )
            workspace.add_songs((song,), workspace.edit_revision)
        review = self.coordinator.prepare_library(
            LibraryPreparationRequest(
                workspace.desired_snapshot(),
                active,
                workspace.generation,
                workspace.revision,
                delete_omissions=False,
                artwork=workspace.artwork_assets,
                media=workspace.media_sources,
            ),
            self.progress,
            cancelled,
        )
        if review.result.prepared is None:
            raise ValueError(
                source_text(
                    "{issues}",
                    issues="\n".join(
                        f"{i.code}: {i.message} {i.detail}"
                        for i in review.result.issues
                    ),
                )
            )
        retained_paths = {t.metadata.location for t in active.library.tracks}
        if any(
            f.action != "write" or f.path in retained_paths for f in review.file_changes
        ):
            raise ValueError(
                source_text(
                    "Append-only import cannot delete or overwrite retained music"
                )
            )
        checkpoint()
        result = self.coordinator.save_library(
            review, active, self.progress, cancelled, retain_recovery=True
        )
        if result.active is None:
            self.pending_recovery = result.recovery_path or None
            detail = "\n".join(
                f"{i.code}: {i.message} {i.detail}" for i in result.issues
            )
            raise ValueError(
                source_text(
                    "{detail}\nRecovery record: {recovery}",
                    detail=detail,
                    recovery=str(result.recovery_path),
                )
            )
        new_tracks = result.active.library.tracks[len(active.library.tracks) :]
        warnings = [f"{i.message} {i.detail}" for i in result.issues]
        try:
            self.history.record(
                identity,
                result.recovery_path,
                tuple(
                    (item.original.sha256, track.metadata.location, track.size_bytes)
                    for (_, item), track in zip(prepared, new_tracks, strict=True)
                ),
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            warnings.append(
                source_text(
                    "Music was written, but the local receipt was not saved: {error}; recovery record: {recovery}",
                    error=str(error),
                    recovery=result.recovery_path,
                )
            )
        self.discard()
        return ImportResult(len(prepared), result.recovery_path, tuple(warnings))

    def restore_last(self, cancelled: Event) -> ActiveIPod:
        self._checkpoint(cancelled)
        if self.pending_recovery:
            self.discard()
            recovered = self.coordinator.recover_sync_journal(self.pending_recovery)
            self.pending_recovery = None
            return recovered
        active, identity = self.active, self._identity()
        recovery = self.history.latest(identity)
        if not recovery:
            raise ValueError(
                source_text("This device has no recoverable import record")
            )
        self.discard()
        self.coordinator.recover_failed_sync(active, recovery, self.progress)
        self.history.restored(identity, recovery)
        candidate = active.candidate.id
        self.coordinator.discover_devices()
        return self.select(candidate)

    def eject(self) -> None:
        self.coordinator.eject_active_ipod(self.active)
        self.discard()

    def discard(self) -> None:
        self._resources.close()
        self._resources = ExitStack()
        self._songs.clear()
        self._entries.clear()
        self._preview_active = None

    def close(self) -> None:
        self.discard()
        self.coordinator.close()
