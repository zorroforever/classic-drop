"""Pure filtering rules for the Classic Drop removal workspace."""

from __future__ import annotations

from dataclasses import dataclass

from iPodDB.library import LibrarySnapshot, MediaKind, Track


@dataclass(frozen=True, slots=True)
class RemovalFilters:
    title: str = ""
    artist: str = ""
    album: str = ""
    genres: tuple[str | None, ...] = ()
    years: tuple[int | None, ...] = ()
    playlists: tuple[int, ...] = ()


def filter_music(
    snapshot: LibrarySnapshot, filters: RemovalFilters
) -> tuple[Track, ...]:
    """Apply AND across dimensions and OR across selected values per dimension."""

    playlist_track_ids = {
        playlist_id: {
            entry.track_id
            for playlist in snapshot.playlists
            if playlist.playlist_id == playlist_id
            for entry in playlist.entries
        }
        for playlist_id in filters.playlists
    }
    title = filters.title.casefold().strip()
    artist = filters.artist.casefold().strip()
    album = filters.album.casefold().strip()
    genres = {
        value.casefold() if isinstance(value, str) else None for value in filters.genres
    }
    years = set(filters.years)
    selected_playlists = set(filters.playlists)

    return tuple(
        track
        for track in snapshot.tracks
        if track.media_kind is MediaKind.MUSIC
        and (not title or title in track.title.casefold())
        and (not artist or artist in track.artist.casefold())
        and (not album or album in track.album.casefold())
        and (not genres or (track.genre.casefold() or None) in genres)
        and (not years or (track.year or None) in years)
        and (
            not selected_playlists
            or any(
                track.track_id in playlist_track_ids[playlist_id]
                for playlist_id in selected_playlists
            )
        )
    )


def removal_media_size(snapshot: LibrarySnapshot, track_ids: tuple[int, ...]) -> int:
    """Count unique media files that no retained Track still references."""

    selected_ids = set(track_ids)
    retained_locations = {
        track.metadata.location.casefold()
        for track in snapshot.tracks
        if track.track_id not in selected_ids and track.metadata.location
    }
    selected_files: dict[str, int] = {}
    for track in snapshot.tracks:
        location = track.metadata.location
        if (
            track.track_id in selected_ids
            and location
            and location.casefold() not in retained_locations
        ):
            key = location.casefold()
            selected_files[key] = max(selected_files.get(key, 0), track.size_bytes)
    return sum(selected_files.values())
