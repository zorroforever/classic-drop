from classic_drop.removal import RemovalFilters, filter_music, removal_media_size
from iPodDB.library import LibrarySnapshot, MediaKind, Track, TrackMetadata
from iPodDB.library.playlists import Playlist, PlaylistEntry


def test_removal_filters_apply_and_across_dimensions_and_or_within_dimensions():
    tracks = (
        Track(
            track_id=1,
            title="Blue Train",
            artist="John Coltrane",
            album="Blue Train",
            length_ms=60000,
            genre="Jazz",
            year=1957,
        ),
        Track(
            track_id=2,
            title="A Love Supreme",
            artist="John Coltrane",
            album="A Love Supreme",
            length_ms=60000,
            genre="Jazz",
            year=1965,
        ),
        Track(
            track_id=3,
            title="Blue in Green",
            artist="Miles Davis",
            album="Kind of Blue",
            length_ms=60000,
            genre="Jazz",
            year=1959,
        ),
    )
    snapshot = LibrarySnapshot(
        tracks,
        (
            Playlist(
                10,
                "Favorites",
                entries=(PlaylistEntry("a", 1), PlaylistEntry("b", 3)),
            ),
            Playlist(
                11, "Coltrane", entries=(PlaylistEntry("c", 1), PlaylistEntry("d", 2))
            ),
        ),
    )

    result = filter_music(
        snapshot,
        RemovalFilters(
            title="blue",
            genres=("Jazz",),
            years=(1957, 1959),
            playlists=(10,),
        ),
    )

    assert tuple(track.track_id for track in result) == (1, 3)
    narrowed = filter_music(
        snapshot,
        RemovalFilters(
            title="blue", artist="miles", genres=("Jazz",), years=(1957, 1959)
        ),
    )
    assert tuple(track.track_id for track in narrowed) == (3,)


def test_removal_filters_can_explicitly_match_missing_genre_and_year():
    tracks = (
        Track(
            track_id=1,
            title="No tags",
            artist="Artist",
            album="Album",
            length_ms=1000,
            genre="",
            year=0,
        ),
        Track(
            track_id=2,
            title="Tagged",
            artist="Artist",
            album="Album",
            length_ms=1000,
            genre="Rock",
            year=2020,
        ),
    )

    result = filter_music(
        LibrarySnapshot(tracks), RemovalFilters(genres=(None,), years=(None,))
    )

    assert tuple(track.track_id for track in result) == (1,)


def test_removal_filters_exclude_non_music_tracks():
    tracks = (
        Track(track_id=1, title="Song", artist="A", album="B", length_ms=1000),
        Track(
            track_id=2,
            title="Episode",
            artist="A",
            album="B",
            length_ms=1000,
            media_types=("podcast",),
        ),
    )

    result = filter_music(LibrarySnapshot(tracks), RemovalFilters())

    assert tuple(track.track_id for track in result) == (1,)
    assert result[0].media_kind is MediaKind.MUSIC


def test_recovery_size_counts_unique_files_and_keeps_shared_media_out():
    tracks = (
        Track(
            track_id=1,
            title="First",
            artist="A",
            album="B",
            length_ms=1,
            size_bytes=100,
            metadata=TrackMetadata(location="iPod_Control/Music/F00/one.m4a"),
        ),
        Track(
            track_id=2,
            title="Shared copy",
            artist="A",
            album="B",
            length_ms=1,
            size_bytes=100,
            metadata=TrackMetadata(location="iPod_Control/Music/F00/shared.m4a"),
        ),
        Track(
            track_id=3,
            title="Retained copy",
            artist="A",
            album="B",
            length_ms=1,
            size_bytes=100,
            metadata=TrackMetadata(location="iPod_Control/Music/F00/shared.m4a"),
        ),
    )

    assert removal_media_size(LibrarySnapshot(tracks), (1, 2)) == 100
