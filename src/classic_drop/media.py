"""Content-bound preparation of only the selected incoming music."""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import mutagen
from PIL import Image, ImageOps

from device_registry import DeviceProfile
from iOpenPod.app.display_text import source_text
from iOpenPod.app.export_tagging import ExportMediaTagger
from iOpenPod.app.media.importing import ImportedSong, MusicImporter
from iOpenPod.app.media.inspection import MediaInspectionError
from iOpenPod.app.media.tags import apply_tag_values, read_tag_values
from iOpenPod.app.media.transcoding import MediaTranscoder, TranscodeSettings
from iPodDB.library import ArtworkPixels, MediaType
from storage import FileFingerprint, HostPath, capture_host_file
from storage.host_input import LocalHostFile

AUDIO_EXTENSIONS = frozenset(
    (
        ".mp3",
        ".m4a",
        ".flac",
        ".wav",
        ".aif",
        ".aiff",
        ".aac",
        ".ogg",
        ".opus",
        ".wma",
        ".ape",
        ".wv",
    )
)


@dataclass(frozen=True, slots=True)
class PreparedSong:
    path: Path
    original: FileFingerprint
    song: ImportedSong
    mode: str
    warnings: tuple[str, ...] = ()


def collect_audio(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    found: dict[Path, None] = {}

    def add(path: Path) -> None:
        if (
            not path.is_symlink()
            and not path.name.startswith(".")
            and path.suffix.lower() in AUDIO_EXTENSIONS
        ):
            found[path.absolute()] = None

    def failed(error: OSError) -> None:
        raise error

    for path in paths:
        path = path.expanduser().absolute()
        if path.is_symlink():
            continue
        if path.is_dir():
            for directory, directories, files in os.walk(
                path, followlinks=False, onerror=failed
            ):
                directories[:] = sorted(
                    d
                    for d in directories
                    if not d.startswith(".") and not (Path(directory) / d).is_symlink()
                )
                for name in sorted(files):
                    add(Path(directory) / name)
        elif path.is_file():
            add(path)
        else:
            raise ValueError(source_text("File not found: {path}", path=str(path)))
    return tuple(found)


def decode_cover(data: bytes) -> ArtworkPixels:
    if len(data) > 32 * 1024 * 1024:
        raise ValueError(source_text("Cover file exceeds 32 MiB"))
    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) > 8192 or image.width * image.height > 32 * 1024 * 1024:
            raise ValueError(source_text("Cover dimensions are too large"))
        # Device thumbnails never need the original multi-megapixel raster.
        oriented = ImageOps.exif_transpose(image)
        oriented.thumbnail((1200, 1200))
        rgb = oriented.convert("RGB")
        return ArtworkPixels(rgb.width, rgb.height, rgb.tobytes())


def embedded_cover(parsed: Any) -> ArtworkPixels | None:
    pictures = list(getattr(parsed, "pictures", ()))
    tags = getattr(parsed, "tags", None)
    if tags is not None:
        if hasattr(tags, "getall"):
            pictures.extend(tags.getall("APIC"))
        else:
            covers = tags.get("covr", ())
            if covers:
                return decode_cover(bytes(covers[0]))
    pictures.sort(key=lambda picture: picture.type != 3)
    for picture in pictures:
        if picture.mime != "-->":
            return decode_cover(picture.data)
    return None


def folder_cover(path: Path, checkpoint: Callable[[], None]) -> ArtworkPixels | None:
    entries = {entry.name.casefold(): entry for entry in path.parent.iterdir()}
    for name in (
        "cover.jpg",
        "cover.png",
        "folder.jpg",
        "folder.png",
        "front.jpg",
        "front.png",
    ):
        candidate = entries.get(name)
        if candidate is not None and candidate.is_file() and not candidate.is_symlink():
            data = LocalHostFile.observe(HostPath(candidate)).read_bytes(
                max_bytes=32 * 1024 * 1024, checkpoint=checkpoint
            )
            return decode_cover(data)
    return None


def prepare_song(
    path: Path,
    profile: DeviceProfile,
    resources: ExitStack,
    checkpoint: Callable[[], None],
) -> PreparedSong:
    source = HostPath(path)
    importer = MusicImporter()
    try:
        song = importer.inspect(source, profile, checkpoint=checkpoint)
    except MediaInspectionError as error:
        if error.code != "media.incompatible":
            raise
    else:
        if song.artwork is None:
            song = replace(song, artwork=folder_cover(path, checkpoint))
        return PreparedSong(path, song.source.fingerprint, _music(song), "copy")

    # Read tags/pixels from the same capture whose fingerprint the transcoder
    # must accept. MP4 conversion may legitimately drop the original tags.
    with capture_host_file(source, checkpoint=checkpoint) as captured:
        original = captured.fingerprint
        with LocalHostFile.observe(captured.snapshot).open_read(
            checkpoint=checkpoint
        ) as stream:
            parsed = mutagen.File(stream)
            tags = read_tag_values(getattr(parsed, "tags", None))
            cover = embedded_cover(parsed)
    transcoder = MediaTranscoder(threads_per_job=2)
    prepared = resources.enter_context(
        transcoder.prepare(
            source,
            profile,
            TranscodeSettings(normalize_44100=True),
            checkpoint=checkpoint,
            expected_source=original,
        )
    )
    song = importer.inspect(prepared.source, profile, checkpoint=checkpoint)
    track = apply_tag_values(song.track, tags, suffix=path.suffix, video=False)
    if not track.title.strip() or track.title == prepared.source.path.stem:
        track = replace(track, title=path.stem)
    cover = cover or folder_cover(path, checkpoint)
    checkpoint()
    ExportMediaTagger().prepare(
        prepared.source,
        track,
        cover,
        file_name=song.track.metadata.location,
    )
    # Tagging changes byte size and hash. Re-inspect the final copy so Storage
    # verifies exactly the bytes that will be published, including embedded art.
    song = importer.inspect(prepared.source, profile, checkpoint=checkpoint)
    song = replace(song, artwork=cover)
    return PreparedSong(path, original, _music(song), "convert", prepared.warnings)


def _music(song: ImportedSong) -> ImportedSong:
    return replace(
        song,
        track=replace(
            song.track,
            media_types=(MediaType.AUDIO,),
            metadata=replace(song.track.metadata, podcast=False),
        ),
    )
