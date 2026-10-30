"""Observe encoded audio headers without compatibility policy or media captures."""

from __future__ import annotations

import io
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

import mutagen
from mutagen.aiff import AIFFInfo
from mutagen.mp3 import MPEGInfo
from mutagen.mp4 import MP4Info
from mutagen.mp4._atom import AtomError, Atoms
from mutagen.wave import WaveStreamInfo

from iOpenPod.app.playback.backend import PlaybackSource


@dataclass(frozen=True, slots=True)
class AudioFormat:
    codec: str = ""
    bit_depth: int | None = None
    sample_rate_hz: int | None = None
    detail: str = ""


class _HeaderReader:
    """A bounded seekable view; large media/tag payloads are skipped, never copied."""

    def __init__(self, source: PlaybackSource, checkpoint: Callable[[], None]) -> None:
        self.source = source
        self.checkpoint = checkpoint
        self.position = 0
        self.remaining = 1024 * 1024
        self.operations = 8192
        self.interrupted: InterruptedError | None = None

    def _check(self) -> None:
        try:
            self.checkpoint()
        except InterruptedError as error:
            self.interrupted = error
            raise
        self.operations -= 1
        if self.operations < 0:
            raise ValueError("Audio metadata exceeds the operation limit")

    def tell(self) -> int:
        self._check()
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self._check()
        base = {
            io.SEEK_SET: 0,
            io.SEEK_CUR: self.position,
            io.SEEK_END: self.source.byte_count,
        }
        if whence not in base or base[whence] + offset < 0:
            raise ValueError("Invalid audio metadata seek")
        self.position = base[whence] + offset
        return self.position

    def read(self, size: int = -1) -> bytes:
        self._check()
        available = max(0, self.source.byte_count - self.position)
        size = available if size < 0 else min(size, available)
        if size > self.remaining:
            raise ValueError("Audio metadata exceeds the read limit")
        result = bytearray()
        while len(result) < size:
            self._check()
            requested = min(size - len(result), 64 * 1024)
            try:
                data = self.source.read_at(self.position, requested)
            except InterruptedError as error:
                self.interrupted = error
                raise
            if not data or len(data) > requested:
                raise OSError("Audio source changed while reading metadata")
            result.extend(data)
            self.position += len(data)
            self.remaining -= len(data)
        return bytes(result)


def inspect_audio_format(
    source: PlaybackSource, *, checkpoint: Callable[[], None]
) -> AudioFormat:
    """Read actual stream facts, including high resolution ALAC and AAC's N/A depth."""
    checkpoint()
    reader = _HeaderReader(source, checkpoint)
    suffix = PurePosixPath(source.file_name).suffix.casefold()
    try:
        if suffix in {".m4a", ".m4b", ".m4p", ".mp4"}:
            info = MP4Info(Atoms(reader), reader)  # type: ignore[no-untyped-call]
            codec = (
                "ALAC"
                if info.codec == "alac"
                else "AAC"
                if info.codec_description.startswith("AAC")
                else info.codec_description or info.codec
            )
            result = AudioFormat(
                codec,
                info.bits_per_sample or None if info.codec == "alac" else None,
                info.sample_rate or None,
            )
        elif suffix == ".mp3":
            mp3 = MPEGInfo(reader)
            result = AudioFormat("MP3", None, mp3.sample_rate or None)
        elif suffix in {".wav", ".aif", ".aiff"}:
            pcm = WaveStreamInfo(reader) if suffix == ".wav" else AIFFInfo(reader)
            result = AudioFormat(
                "PCM", pcm.bits_per_sample or None, pcm.sample_rate or None
            )
        else:
            return AudioFormat(
                detail="Audio header inspection is unavailable for this format"
            )
    except InterruptedError:
        raise
    except (
        mutagen.MutagenError,
        AtomError,
        OSError,
        ValueError,
        struct.error,
        EOFError,
        RecursionError,
    ) as error:
        # Mutagen converts OSError (including InterruptedError) to parser errors.
        if reader.interrupted is not None:
            raise reader.interrupted from error
        return AudioFormat(detail=str(error) or "Audio header could not be read")
    checkpoint()
    return result
