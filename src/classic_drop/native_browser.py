"""Disposable pure-metadata index for the native helper; no device or Qt I/O."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from threading import Event

from iPodDB.library import LibrarySnapshot, Track


def metadata_values(value: object) -> tuple[str, ...]:
    if isinstance(value, (date, datetime)):
        return (value.isoformat(),)
    if isinstance(value, Enum):
        return (str(value.value),)
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, bool) or value is None:
        return ()
    if isinstance(value, (int, float)):
        return (str(value),) if value else ()
    if isinstance(value, tuple):
        return tuple(text for item in value for text in metadata_values(item))
    if is_dataclass(value):
        return tuple(
            text
            for item in fields(value)
            for text in metadata_values(getattr(value, item.name))
        )
    return ()


def search_text(track: Track) -> str:
    return " ".join(
        " ".join(
            text
            for item in fields(track)
            if item.name not in {"track_id", "artwork_id", "media_types", "ipod"}
            for text in metadata_values(getattr(track, item.name))
        )
        .casefold()
        .split()
    )


@dataclass(frozen=True, slots=True)
class NativeBrowserIndex:
    tracks: tuple[Track, ...]
    search: dict[int, str]
    albums: dict[str, tuple[Track, ...]]


def build_index(
    snapshot: LibrarySnapshot,
    cancelled: Event,
    progress: Callable[[int, int], None] = lambda *_: None,
) -> NativeBrowserIndex:
    tracks = tuple(
        sorted(
            snapshot.tracks,
            key=lambda t: (
                t.album_key,
                t.metadata.disc_number,
                t.track_number,
                t.title.casefold(),
            ),
        )
    )
    search: dict[int, str] = {}
    groups: dict[str, list[Track]] = {}
    for completed, track in enumerate(tracks, 1):
        if cancelled.is_set():
            raise InterruptedError("Browser preparation cancelled")
        search[track.track_id] = search_text(track)
        groups.setdefault(track.album_key, []).append(track)
        progress(completed, len(tracks))
    if cancelled.is_set():
        raise InterruptedError("Browser preparation cancelled")
    return NativeBrowserIndex(
        tracks, search, {key: tuple(value) for key, value in groups.items()}
    )
