"""Bounded metadata candidate lookup for Classic Drop import review."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from iPodDB.library import Track


class MetadataCandidateIndex:
    """Index title/artist once, then apply the duration candidate threshold."""

    def __init__(self, tracks: Iterable[Track]) -> None:
        self._index: dict[tuple[str, str], list[Track]] = defaultdict(list)
        for candidate in tracks:
            key = _identity(candidate.title, candidate.artist)
            if all(key):
                self._index[key].append(candidate)

    def find(self, track: Track) -> tuple[Track, ...]:
        key = _identity(track.title, track.artist)
        if not all(key) or track.length_ms <= 0:
            return ()
        return tuple(
            candidate
            for candidate in self._index.get(key, ())
            if candidate.length_ms > 0
            and abs(candidate.length_ms - track.length_ms) < 1500
        )


def _identity(title: str, artist: str) -> tuple[str, str]:
    return title.strip().casefold(), artist.strip().casefold()
