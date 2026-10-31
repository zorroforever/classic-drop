import io
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from classic_drop.audio_format import AudioFormat, inspect_audio_format


@dataclass
class Source:
    data: bytes
    file_name: str = "audio.m4a"
    reads: list[tuple[int, int]] = field(default_factory=list)

    @property
    def byte_count(self) -> int:
        return len(self.data)

    def read_at(self, offset: int, length: int) -> bytes:
        self.reads.append((offset, length))
        return self.data[offset : offset + length]


def encoded_audio(tmp_path: Path, codec: str, rate: int, bits: int) -> bytes:
    path = tmp_path / f"{codec}-{rate}-{bits}.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate={rate}:duration=0.1",
            "-c:a",
            codec,
            "-sample_fmt",
            "s32p" if bits == 24 else "s16p",
            str(path),
        ]
        if codec == "alac"
        else [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate={rate}:duration=0.1",
            "-c:a",
            codec,
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


@pytest.mark.parametrize(
    ("codec", "rate", "bits", "expected"),
    [
        ("alac", 44100, 16, AudioFormat("ALAC", 16, 44100)),
        ("alac", 48000, 24, AudioFormat("ALAC", 24, 48000)),
        ("alac", 96000, 24, AudioFormat("ALAC", 24, 96000)),
        ("aac", 48000, 16, AudioFormat("AAC", None, 48000)),
    ],
)
def test_reads_real_encoding_without_applying_import_limits(
    tmp_path: Path, codec: str, rate: int, bits: int, expected: AudioFormat
) -> None:
    source = Source(encoded_audio(tmp_path, codec, rate, bits))

    assert inspect_audio_format(source, checkpoint=lambda: None) == expected


def test_skips_large_payload_and_metadata_padding(tmp_path: Path) -> None:
    data = encoded_audio(tmp_path, "alac", 96000, 24)
    stream = io.BytesIO(data)
    moov = 0
    while stream.tell() < len(data):
        start = stream.tell()
        size = int.from_bytes(stream.read(4), "big")
        name = stream.read(4)
        if name == b"moov":
            moov = start
            break
        stream.seek(start + size)
    assert moov > 0
    padding = (
        (8 * 1024 * 1024).to_bytes(4, "big") + b"free" + bytes(8 * 1024 * 1024 - 8)
    )
    source = Source(data[:moov] + padding + data[moov:])

    assert inspect_audio_format(source, checkpoint=lambda: None) == AudioFormat(
        "ALAC", 24, 96000
    )
    assert sum(length for _, length in source.reads) < 64 * 1024


def test_corrupt_media_reports_unknown_instead_of_inventing_16_bit() -> None:
    result = inspect_audio_format(Source(b"broken"), checkpoint=lambda: None)

    assert result.codec == ""
    assert result.bit_depth is None
    assert result.sample_rate_hz is None
    assert result.detail


def test_cancellation_propagates_instead_of_caching_unknown() -> None:
    def cancelled() -> None:
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError, match="cancelled"):
        inspect_audio_format(Source(bytes(10)), checkpoint=cancelled)


def test_pathological_atom_count_is_bounded() -> None:
    source = Source((8).to_bytes(4, "big") + b"free")
    source.data *= 10000
    result = inspect_audio_format(source, checkpoint=lambda: None)
    assert result.codec == ""
    assert "limit" in result.detail
    assert len(source.reads) < 8192


@pytest.mark.parametrize(
    ("suffix", "codec", "bits"),
    [("wav", "pcm_s24le", 24), ("aiff", "pcm_s16be", 16), ("mp3", "libmp3lame", None)],
)
def test_pcm_and_mp3_report_real_header_facts(
    tmp_path: Path, suffix: str, codec: str, bits: int | None
) -> None:
    path = tmp_path / f"audio.{suffix}"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=sample_rate=44100:duration=0.1",
            "-c:a",
            codec,
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    result = inspect_audio_format(
        Source(path.read_bytes(), path.name), checkpoint=lambda: None
    )
    assert result == AudioFormat("MP3" if suffix == "mp3" else "PCM", bits, 44100)


def test_cancellation_during_header_reads_is_not_unknown(tmp_path: Path) -> None:
    source = Source(encoded_audio(tmp_path, "alac", 96000, 24))

    def checkpoint() -> None:
        if len(source.reads) > 3:
            raise InterruptedError("cancelled mid-read")

    with pytest.raises(InterruptedError, match="mid-read"):
        inspect_audio_format(source, checkpoint=checkpoint)


@pytest.mark.parametrize(
    "data", [b"broken media", b"\x00\x00\x00\x04moov", b"\x00\x00\x00\x10moov12345678"]
)
def test_malformed_container_atoms_report_unknown(data: bytes) -> None:
    result = inspect_audio_format(Source(data), checkpoint=lambda: None)
    assert result.codec == ""
    assert result.detail
