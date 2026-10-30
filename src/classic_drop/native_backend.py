"""Serial, authoritative native-shell adapter over the existing engine."""

from __future__ import annotations

import base64
import io
import json
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4

from PIL import Image
from PySide6.QtCore import QCoreApplication

from classic_drop.engine import ClassicDropEngine, PreviewEntry, RemovalReview
from classic_drop.media import decode_cover
from classic_drop.native_browser import NativeBrowserIndex, build_index
from classic_drop.native_protocol import (
    AlbumDTO,
    DeviceDTO,
    FacetDTO,
    PreviewDTO,
    Request,
    Result,
    ReviewDTO,
    StateDTO,
    TrackDTO,
)
from classic_drop.removal import RemovalFilters, filter_music
from iOpenPod.app.models.artwork import ArtworkRequest
from iOpenPod.app.models.device import ActiveIPod, DeviceCandidateId
from iPodDB.library import ArtworkPixels, Track
from storage import HostPath
from storage.host_input import LocalHostFile


def track_dto(track: Track, source: str = "", search: str = "") -> TrackDTO:
    return TrackDTO(
        str(track.track_id),
        track.title,
        track.artist,
        track.album,
        track.album_artist,
        track.album_key,
        track.genre,
        track.year,
        track.track_number,
        track.metadata.disc_number,
        track.length_ms,
        track.size_bytes,
        str(track.artwork_id),
        source,
        track.media_kind.value,
        search,
    )


def preview_dto(entry: PreviewEntry) -> PreviewDTO:
    return PreviewDTO(
        entry.token,
        str(entry.path),
        entry.title,
        entry.artist,
        entry.album,
        entry.album_artist,
        entry.track_number,
        entry.disc_number,
        entry.selected,
        entry.status,
        entry.mode,
        entry.length_ms,
        entry.size_bytes,
        str(entry.detail),
        entry.artwork is not None,
    )


def thumbnail(pixels: ArtworkPixels | None) -> str:
    if pixels is None:
        return ""
    image = Image.frombytes("RGB", (pixels.width, pixels.height), pixels.rgb888)
    image.thumbnail((320, 320))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    if len(data) > 512 * 1024:
        raise ValueError("Thumbnail exceeds 512 KiB")
    return base64.b64encode(data).decode("ascii")


class NativeBackend:
    def __init__(self, engine: ClassicDropEngine) -> None:
        self.engine = engine
        self.generation = uuid4().hex
        self.revision = uuid4().hex
        self._active: ActiveIPod | None = engine.coordinator.active_ipod
        self.entries: dict[str, PreviewEntry] = {}
        self.package: dict[int, str] = {}
        self.review: RemovalReview | None = None
        self.review_token = ""
        self.review_rows: tuple[TrackDTO, ...] = ()
        self.browser: NativeBrowserIndex | None = None
        self.browser_lock = Lock()

    def _sync(self) -> None:
        active = self.engine.coordinator.active_ipod
        if active is not self._active:
            self._active = active
            self.generation = uuid4().hex
            self.revision = uuid4().hex
            with self.browser_lock:
                self.browser = None
            self.entries.clear()
            self.package.clear()
            self._invalidate_review()

    def browser_source(self, request: Request) -> tuple[ActiveIPod, str, Result]:
        self._sync()
        if request.generation != self.generation:
            raise ValueError("The device or Library generation expired; reload")
        return self.engine.active, self.generation, self._result()

    def publish_browser(
        self,
        active: ActiveIPod,
        generation: str,
        index: NativeBrowserIndex,
        cancelled: Event,
    ) -> bool:
        with self.browser_lock:
            if (
                cancelled.is_set()
                or active is not self._active
                or generation != self.generation
            ):
                return False
            self.browser = index
            return True

    def _invalidate_review(self) -> None:
        self.review = None
        self.review_token = ""
        self.review_rows = ()

    def state(self) -> StateDTO:
        self._sync()
        active = self._active
        candidate = (
            self.engine.coordinator.discovery.candidate(active.candidate.id)
            or active.candidate
            if active is not None
            else None
        )
        recovery = self.engine.pending_recovery or ""
        allowed = False
        can_keep = False
        if active is not None:
            operation = self.engine.history.latest_operation(self.engine._identity())
            if operation:
                recovery = recovery or operation[0]
                can_keep = operation[1] == "delete" and not self.engine.pending_recovery
            try:
                self.engine._require_writes_allowed()
                allowed = True
            except ValueError:
                pass
        return StateDTO(
            self.generation,
            self.revision,
            active.candidate.id.value if active else "",
            active.display_name if active else "",
            candidate.available_bytes if candidate else 0,
            candidate.total_bytes if candidate else 0,
            len(active.library.tracks) if active else 0,
            len(self.entries),
            len(self.package),
            bool(recovery),
            allowed,
            recovery,
            can_keep,
        )

    def _result(
        self,
        *,
        devices: tuple[DeviceDTO, ...] = (),
        tracks: tuple[TrackDTO, ...] = (),
        albums: tuple[AlbumDTO, ...] = (),
        preview: tuple[PreviewDTO, ...] = (),
        genres: tuple[str, ...] = (),
        years: tuple[int, ...] = (),
        playlists: tuple[FacetDTO, ...] = (),
        review: ReviewDTO | None = None,
        total: int = 0,
        offset: int = 0,
        image: str = "",
        count: int = 0,
        warnings: tuple[str, ...] = (),
    ) -> Result:
        return Result(
            self.state(),
            devices,
            tracks,
            albums,
            preview,
            genres,
            years,
            playlists,
            review,
            total,
            offset,
            image,
            count,
            warnings,
        )

    def execute(self, request: Request, cancelled: Event) -> Result:
        self._sync()
        command = request.command
        if (
            command not in {"hello", "discover", "select", "close"}
            and request.generation != self.generation
        ):
            raise ValueError("The device or Library generation expired; reload")
        if command == "hello":
            return replace(
                self._result(), gui_application=QCoreApplication.instance() is not None
            )
        self.engine._checkpoint(cancelled)
        if command == "discover":
            # Passive discovery must not replace the Active iPod merely because
            # capacity changed: previews and Reviews bind to that exact object.
            # Storage still invalidates disconnected Filesystem Sessions.
            devices = self.engine.discover(
                refresh_known=False, automatic=request.source != "manual"
            )
            return self._result(
                warnings=tuple(str(issue.detail) for issue in devices.mount_issues),
                devices=tuple(
                    DeviceDTO(
                        c.id.value,
                        c.display_name,
                        c.profile_name or c.readiness.value,
                        c.selectable,
                        c.available_bytes,
                        c.total_bytes,
                    )
                    for c in devices
                ),
            )
        if command == "select":
            self.engine.select(DeviceCandidateId(request.token))
            return self._result()
        if command == "validate":
            with self.engine.coordinator.sync_session(self.engine.active):
                self.engine._checkpoint(cancelled)
            return self._result()
        if command == "eject":
            self.engine.eject()
            return self._result()
        if command == "restore":
            self.engine.restore_last(cancelled)
            return self._result()
        if command == "keep":
            self.engine.keep_current_contents(request.token, cancelled)
            self._invalidate_review()
            return self._result()
        if command == "discard":
            self.engine.discard()
            self.entries.clear()
            self.revision = uuid4().hex
            return self._result()
        if command == "preview":
            paths = tuple(e.path for e in self.entries.values()) + tuple(
                Path(p) for p in request.paths
            )
            entries = self.engine.preview(paths, cancelled)
            old = self.entries
            self.entries = {e.token: old.get(e.token, e) for e in entries}
            self.revision = uuid4().hex
            return self._preview_page(request)
        if command == "queue":
            return self._preview_page(request)
        if command in {"edit", "commit"}:
            self._apply_edits(request)
            if command == "edit":
                self.revision = uuid4().hex
                return self._result()
            if request.ids and set(request.ids) != set(self.entries):
                raise ValueError("The preview set expired; reload")
            result = self.engine.commit(tuple(self.entries.values()), cancelled)
            return self._result(count=result.added, warnings=result.warnings)
        if command in {"cover", "clear_cover"}:
            if (
                request.revision != self.revision
                or not request.ids
                or not set(request.ids) <= self.entries.keys()
            ):
                raise ValueError("The preview expired; reload")
            pixels = None
            if command == "cover":
                if len(request.paths) != 1:
                    raise ValueError("Choose one cover")
                data = LocalHostFile.observe(
                    HostPath(Path(request.paths[0]))
                ).read_bytes(
                    max_bytes=32 * 1024 * 1024,
                    checkpoint=lambda: self.engine._checkpoint(cancelled),
                )
                pixels = decode_cover(data)
            for token in request.ids:
                self.entries[token] = replace(self.entries[token], artwork=pixels)
            self.revision = uuid4().hex
            return self._result()
        if command == "preview_artwork":
            entry = self.entries.get(request.token)
            if entry is None:
                raise ValueError("The preview expired; reload")
            return self._result(image=thumbnail(entry.artwork))
        if command == "artwork":
            artwork = self.engine.coordinator.load_artwork(
                ArtworkRequest(int(request.token), 320)
            )
            pixels = (
                ArtworkPixels(artwork.width, artwork.height, artwork.rgb888)
                if artwork
                else None
            )
            return self._result(image=thumbnail(pixels))
        if command in {"tracks", "albums", "facets", "filter", "package"}:
            return self._browse(request, cancelled)
        if command in {"package_add", "package_remove", "package_clear"}:
            tracks = {t.track_id: t for t in self.engine.active.library.tracks}
            ids = tuple(int(value) for value in request.ids)
            if command == "package_clear":
                self.package.clear()
            elif command == "package_remove":
                for track_id in ids:
                    self.package.pop(track_id, None)
            else:
                if not ids or any(
                    i not in tracks or tracks[i].media_kind.value != "music"
                    for i in ids
                ):
                    raise ValueError("Select current Music Tracks")
                for track_id in ids:
                    self.package.setdefault(track_id, request.source)
            self._invalidate_review()
            return self._result()
        if command == "prepare_delete":
            active = self.engine.active
            review = self.engine.prepare_removal(
                tuple(self.package),
                cancelled,
                active.library,
                active.candidate.id.value,
                active.database_fingerprint.sha256,
            )
            self.review = review
            self.review_token = uuid4().hex
            reviewed_ids = set(review.track_ids)
            # Capture all rows once in the same ordering as the paged browser.
            self.review_rows = tuple(
                track_dto(t, self.package[t.track_id])
                for t in sorted(
                    (t for t in active.library.tracks if t.track_id in reviewed_ids),
                    key=lambda t: (
                        t.album_key,
                        t.metadata.disc_number,
                        t.track_number,
                        t.title.casefold(),
                    ),
                )
            )
            dto = ReviewDTO(
                self.review_token,
                review.size_bytes,
                self.review_rows[:200],
                tuple(
                    p.name
                    for p in active.library.playlists
                    if any(e.track_id in reviewed_ids for e in p.entries)
                ),
                len(self.review_rows),
            )
            return self._result(review=dto, total=len(reviewed_ids))
        if command == "review":
            if (
                not self.review
                or request.token != self.review_token
                or self.review.source is not self.engine.active
            ):
                raise ValueError("The removal Review expired; rebuild it")
            return self._result(
                tracks=self.review_rows[
                    request.offset : request.offset + request.limit
                ],
                total=len(self.review_rows),
                offset=request.offset,
            )
        if command == "delete":
            if (
                not self.review
                or not request.token
                or request.token != self.review_token
            ):
                raise ValueError("The removal Review expired; rebuild it")
            review = self.review
            self._invalidate_review()
            deletion = self.engine.commit_removal(review, cancelled)
            return self._result(count=deletion.removed)
        raise ValueError(f"Unknown command: {command}")

    def _apply_edits(self, request: Request) -> None:
        if request.revision != self.revision:
            raise ValueError("The preview revision expired; reload")
        edits = {e.token: e for e in request.edits}
        if len(edits) != len(request.edits) or not edits.keys() <= self.entries.keys():
            raise ValueError("The preview tokens expired; reload")
        updated = dict(self.entries)
        for token, edit in edits.items():
            entry = updated[token]
            if edit.selected and (
                entry.status == "error"
                or (entry.status != "new" and not edit.allow_duplicate)
            ):
                raise ValueError("Explicit duplicate override is required")
            updated[token] = replace(
                entry,
                title=edit.title,
                artist=edit.artist,
                album=edit.album,
                album_artist=edit.album_artist,
                track_number=edit.track_number,
                disc_number=edit.disc_number,
                selected=edit.selected,
            )
        self.entries = updated

    def _preview_page(self, request: Request) -> Result:
        entries = tuple(self.entries.values())
        return self._result(
            preview=tuple(
                preview_dto(e)
                for e in entries[request.offset : request.offset + request.limit]
            ),
            total=len(entries),
            offset=request.offset,
        )

    def _browse(self, request: Request, cancelled: Event) -> Result:
        snapshot = self.engine.active.library
        if self.browser is None:
            self.browser = build_index(snapshot, cancelled)
        browser = self.browser
        if request.command == "facets":
            return self._result(
                genres=tuple(sorted({t.genre for t in snapshot.tracks})),
                years=tuple(sorted({t.year for t in snapshot.tracks}, reverse=True)),
                playlists=tuple(
                    FacetDTO(str(p.playlist_id), p.name) for p in snapshot.playlists
                ),
            )
        if request.command == "filter":
            tracks = filter_music(
                snapshot,
                RemovalFilters(
                    request.title,
                    request.artist,
                    request.album_filter,
                    request.genres,
                    request.years,
                    tuple(int(p) for p in request.playlists),
                ),
            )
        elif request.command == "package":
            tracks = tuple(t for t in snapshot.tracks if t.track_id in self.package)
        else:
            tracks = browser.tracks
        if request.command == "albums":
            groups: dict[str, list[Track]] = {}
            for track in tracks:
                groups.setdefault(track.album_key, []).append(track)
            albums = []
            for key, members in groups.items():
                members.sort(
                    key=lambda t: (
                        t.metadata.disc_number,
                        t.track_number,
                        t.title.casefold(),
                    )
                )
                first = members[0]
                if not any(
                    request.query.casefold().strip() in browser.search[t.track_id]
                    for t in members
                ):
                    continue
                albums.append(
                    AlbumDTO(
                        key,
                        first.album,
                        first.effective_album_artist,
                        next((t.year for t in members if t.year > 0), 0),
                        len(members),
                        sum(max(0, t.length_ms) for t in members),
                        str(
                            next((t.artwork_id for t in members if t.artwork_id > 0), 0)
                        ),
                    )
                )
            albums.sort(key=lambda a: (a.title.casefold(), a.artist.casefold()))
            fitted_albums: list[AlbumDTO] = []
            album_size = 0
            for album_row in albums[request.offset : request.offset + request.limit]:
                row_size = len(
                    json.dumps(asdict(album_row), ensure_ascii=False).encode("utf-8")
                )
                if album_size + row_size > 900_000:
                    if not fitted_albums:
                        raise ValueError(
                            "An Album metadata record exceeds the native transport limit"
                        )
                    break
                fitted_albums.append(album_row)
                album_size += row_size
            return self._result(
                albums=tuple(fitted_albums),
                total=len(albums),
                offset=request.offset,
            )
        if request.album:
            tracks = tuple(t for t in tracks if t.album_key == request.album)
        query = request.query.casefold().strip()
        tracks = tuple(
            sorted(
                (t for t in tracks if query in browser.search[t.track_id]),
                key=lambda t: (
                    t.album_key,
                    t.metadata.disc_number,
                    t.track_number,
                    t.title.casefold(),
                ),
            )
        )
        page = tuple(
            track_dto(
                t,
                self.package.get(t.track_id, ""),
                browser.search[t.track_id] if request.command == "tracks" else "",
            )
            for t in tracks[request.offset : request.offset + request.limit]
        )
        # Leave room for state, envelope and JSON escaping without truncating metadata.
        fitted: list[TrackDTO] = []
        size = 0
        for row in page:
            row_size = len(json.dumps(asdict(row), ensure_ascii=False).encode("utf-8"))
            if size + row_size > 900_000:
                if not fitted:
                    raise ValueError(
                        "A Track metadata record exceeds the native transport limit"
                    )
                break
            fitted.append(row)
            size += row_size
        return self._result(
            tracks=tuple(fitted), total=len(tracks), offset=request.offset
        )
