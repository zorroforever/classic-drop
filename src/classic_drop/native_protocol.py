"""Versioned, bounded DTOs shared with the native shell; no GUI imports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

VERSION = 1
MAX_MESSAGE = 1024 * 1024
MAX_PAGE = 200


@dataclass(frozen=True, slots=True)
class Edit:
    token: str
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    track_number: int = 0
    disc_number: int = 0
    selected: bool = False
    allow_duplicate: bool = False


@dataclass(frozen=True, slots=True)
class Request:
    id: str
    command: str
    generation: str = ""
    revision: str = ""
    token: str = ""
    paths: tuple[str, ...] = ()
    ids: tuple[str, ...] = ()
    edits: tuple[Edit, ...] = ()
    query: str = ""
    album: str = ""
    offset: int = 0
    limit: int = MAX_PAGE
    title: str = ""
    artist: str = ""
    album_filter: str = ""
    genres: tuple[str | None, ...] = ()
    years: tuple[int | None, ...] = ()
    playlists: tuple[str, ...] = ()
    source: str = ""
    version: int = VERSION
    allow_high_resolution_alac: bool = False

    @classmethod
    def decode(cls, data: bytes) -> Request:
        if len(data) > MAX_MESSAGE:
            raise ValueError("Message exceeds 1 MiB")
        raw: Any = json.loads(data)
        if not isinstance(raw, dict) or raw.get("version") != VERSION:
            raise ValueError("Unsupported protocol version")
        allowed = set(cls.__dataclass_fields__)
        if set(raw) - allowed or not raw.get("id") or not raw.get("command"):
            raise ValueError("Invalid command envelope")
        values: dict[str, Any] = {}
        for name, value in raw.items():
            if name == "allow_high_resolution_alac":
                if type(value) is not bool:
                    raise ValueError("Invalid ALAC original import option")
            elif name in {"offset", "limit", "version"}:
                if type(value) is not int or value < 0:
                    raise ValueError(f"Invalid {name}")
            elif name == "edits":
                if not isinstance(value, list):
                    raise ValueError("Invalid edits")
                value = tuple(_edit(item) for item in value)
            elif name in {"paths", "ids", "playlists", "genres", "years"}:
                if not isinstance(value, list) or len(value) > 20000:
                    raise ValueError(f"Invalid {name}")
                expected = int if name == "years" else str
                if any(
                    type(item) is not expected
                    and not (item is None and name in {"genres", "years"})
                    for item in value
                ):
                    raise ValueError(f"Invalid {name}")
                value = tuple(value)
            elif not isinstance(value, str) or len(value) > 16384:
                raise ValueError(f"Invalid {name}")
            values[name] = value
        request = cls(**values)
        if not 1 <= request.limit <= MAX_PAGE:
            raise ValueError("Page must contain 1–200 items")
        return request


def _edit(raw: Any) -> Edit:
    if not isinstance(raw, dict) or not isinstance(raw.get("token"), str):
        raise ValueError("Invalid edit token")
    if set(raw) - set(Edit.__dataclass_fields__):
        raise ValueError("Unknown edit field")
    for name, value in raw.items():
        expected = (
            bool
            if name in {"selected", "allow_duplicate"}
            else int
            if name in {"track_number", "disc_number"}
            else str
        )
        if type(value) is not expected:
            raise ValueError(f"Invalid edit {name}")
        if isinstance(value, int) and not 0 <= value <= 65535:
            raise ValueError(f"Invalid edit {name}")
        if isinstance(value, str) and len(value) > 16384:
            raise ValueError("Edit text too long")
    return Edit(**raw)


@dataclass(frozen=True, slots=True)
class DeviceDTO:
    id: str
    name: str
    detail: str
    selectable: bool
    available_bytes: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class TrackDTO:
    id: str
    title: str
    artist: str
    album: str
    album_artist: str
    album_id: str
    genre: str
    year: int
    track_number: int
    disc_number: int
    length_ms: int
    size_bytes: int
    artwork_id: str
    source: str = ""
    media_kind: str = "music"
    search_text: str = ""


@dataclass(frozen=True, slots=True)
class AlbumDTO:
    id: str
    title: str
    artist: str
    year: int
    track_count: int
    duration_ms: int
    artwork_id: str


@dataclass(frozen=True, slots=True)
class PreviewDTO:
    token: str
    path: str
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int
    disc_number: int
    selected: bool
    status: str
    mode: str
    length_ms: int
    size_bytes: int
    detail: str
    has_artwork: bool


@dataclass(frozen=True, slots=True)
class StateDTO:
    generation: str
    revision: str
    active_id: str
    active_name: str
    available_bytes: int
    total_bytes: int
    track_count: int
    queue_count: int
    package_count: int
    can_restore: bool
    writes_allowed: bool
    recovery_path: str
    can_keep_contents: bool = False


@dataclass(frozen=True, slots=True)
class ReviewDTO:
    token: str
    size_bytes: int
    tracks: tuple[TrackDTO, ...]
    playlists: tuple[str, ...]
    track_count: int


@dataclass(frozen=True, slots=True)
class FacetDTO:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class AudioFormatDTO:
    id: str
    codec: str
    bit_depth: int | None
    sample_rate_hz: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class Result:
    state: StateDTO
    devices: tuple[DeviceDTO, ...] = ()
    tracks: tuple[TrackDTO, ...] = ()
    albums: tuple[AlbumDTO, ...] = ()
    preview: tuple[PreviewDTO, ...] = ()
    genres: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    playlists: tuple[FacetDTO, ...] = ()
    review: ReviewDTO | None = None
    total: int = 0
    offset: int = 0
    image: str = ""
    count: int = 0
    warnings: tuple[str, ...] = ()
    gui_application: bool = False
    audio_formats: tuple[AudioFormatDTO, ...] = ()


@dataclass(frozen=True, slots=True)
class ProgressDTO:
    phase: str
    message: str
    completed: int | None
    total: int | None
    current_item: str
    unit: str
    fraction: float | None = None
    measurement: str = ""


@dataclass(frozen=True, slots=True)
class Envelope:
    id: str
    event: str
    generation: str
    sequence: int
    result: Result | None = None
    progress: ProgressDTO | None = None
    code: str = ""
    detail: str = ""
    version: int = field(default=VERSION, init=False)
